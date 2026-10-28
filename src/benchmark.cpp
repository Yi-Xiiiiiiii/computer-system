#include "adaptive_search.h"
#include "linux_aligned_file_reader.h"
#include <fstream>
#include <iostream>
#include <iomanip>

int main(int argc,char **argv) {
 try {
  // Baseline and optimization share this driver, index and timing implementation.
  if (argc!=10) throw std::runtime_error(
    "Usage: benchmark PREFIX BASE_META WORKLOAD graph|adaptive L M THRESHOLD OUTPUT.csv OUTPUT.ids.ibin");
  const std::string prefix=argv[1], meta=argv[2], workload=argv[3], policy=argv[4];
  size_t L=std::stoul(argv[5]), m=std::stoul(argv[6]); double threshold=std::stod(argv[7]);
  if ((policy!="graph" && policy!="adaptive") || L<10 || m<10 || !std::isfinite(threshold) || threshold<0 || threshold>1)
    throw std::runtime_error("Invalid policy/L/M/threshold");
  adaptive::check_identity_layout(prefix);
  constexpr size_t k=10; constexpr uint32_t beam=8;
  omp_set_num_threads(1);
  uint8_t *queries_raw=nullptr; size_t nq,dim;
  pipeann::load_bin<uint8_t>(workload+"/query.u8bin",queries_raw,nq,dim);
  std::unique_ptr<uint8_t[]> queries(queries_raw);
  // Reuse checked CSR parser to invert query labels; require course single-label queries.
  adaptive::LabelPostings query_posts; query_posts.load(workload+"/query.metadata.spmat");
  if (query_posts.nodes!=nq || query_posts.ids.size()!=nq) throw std::runtime_error("Require one label per query");
  std::vector<uint32_t> labels(nq,UINT32_MAX);
  for (size_t label=0; label+1<query_posts.offsets.size(); ++label)
    for (size_t j=query_posts.offsets[label]; j<query_posts.offsets[label+1]; ++j) {
      auto q=query_posts.ids[j];
      if (labels[q]!=UINT32_MAX) throw std::runtime_error("Multi-label query unsupported by extension");
      labels[q]=label;
    }
  for (auto label:labels) if (label==UINT32_MAX) throw std::runtime_error("Unlabelled query unsupported");
  std::shared_ptr<AlignedFileReader> reader(new LinuxAlignedFileReader());
  std::unique_ptr<pipeann::AbstractNeighbor<uint8_t>> pq(pipeann::get_nbr_handler<uint8_t>(pipeann::Metric::L2,"pq"));
  pipeann::SSDIndex<uint8_t> index(pipeann::Metric::L2,reader,pq.get(),true);
  if (index.load(prefix.c_str(),1,true)!=0) throw std::runtime_error("Index load failed");
  if (dim!=index.meta_.data_dim) throw std::runtime_error("Query dimension mismatch");
  index.load_spmat_filter_store(meta); index.build_full_adj(32); index.set_filter_precheck(true);
  adaptive::LabelPostings postings; double build_us=0;
  if (policy=="adaptive") {
    const auto start=adaptive::Clock::now(); postings.load(meta); build_us=adaptive::us(start);
    if (postings.nodes!=index.meta_.npoints) throw std::runtime_error("Base metadata size mismatch");
  }
  std::vector<uint32_t> results(nq*k,UINT32_MAX);
  std::vector<adaptive::Metrics> stats(nq);
  std::vector<double> skips(nq),tunnel(nq);
  const auto phase_start=adaptive::Clock::now();
  for (size_t q=0; q<nq; ++q) {
    auto start=adaptive::Clock::now(); auto route_start=start;
    bool enumerate=policy=="adaptive" && adaptive::should_enumerate(postings.count(labels[q]),postings.nodes,threshold);
    stats[q].route_us=adaptive::us(route_start);
    uint32_t qlabels[2]={1,labels[q]};
    if (enumerate) adaptive::search(index,*pq,*reader,postings,queries.get()+q*dim,labels[q],k,m,beam,results.data()+q*k,stats[q]);
    else {
      pipeann::QueryStats s{};
      index.pipe_search(queries.get()+q*dim,k,0,L,results.data()+q*k,nullptr,beam,&s,nullptr,qlabels);
      stats[q].ios=s.n_ios; skips[q]=s.n_filter_skip; tunnel[q]=s.bd_tunnel_us;
    }
    stats[q].query_us=adaptive::us(start);
  }
  const double phase_us=adaptive::us(phase_start);
  // Ground truth is first opened AFTER search completes; it is never candidate input.
  std::ifstream gt(workload+"/ground_truth.ids.ibin",std::ios::binary);
  uint32_t hdr[2]; adaptive::read_exact(gt,hdr,2);
  if (hdr[0]!=nq || hdr[1]<k) throw std::runtime_error("GT dimensions mismatch");
  std::vector<uint32_t> truth(size_t(hdr[0])*hdr[1]); adaptive::read_exact(gt,truth.data(),truth.size());
  auto *store=index.get_spmat_filter();
  std::ofstream out(argv[8]); if (!out) throw std::runtime_error("Cannot write CSV");
  out<<"query_id,label_id,recall_percent,query_us,route_us,pq_us,rerank_us,candidates,reranked,logical_ios,filter_skips,tunnel_us,enumerated,query_phase_us,postings_build_us,postings_bytes\n";
  out<<std::setprecision(12);
  for (size_t q=0; q<nq; ++q) {
    std::set<uint32_t> expected,returned; size_t hits=0;
    for (size_t j=0;j<k;++j) if (truth[q*hdr[1]+j]!=UINT32_MAX) expected.insert(truth[q*hdr[1]+j]);
    uint32_t qlabels[2]={1,labels[q]};
    for (size_t j=0;j<k;++j) {
      auto id=results[q*k+j]; if(id==UINT32_MAX) continue;
      if(id>=index.meta_.npoints || !returned.insert(id).second || !store->passes(id,qlabels))
        throw std::runtime_error("Invalid, duplicate or nonmatching result ID");
      hits+=expected.count(id);
    }
    auto &s=stats[q];
    out<<q<<','<<labels[q]<<','<<(expected.empty()?0:100.0*hits/expected.size())<<','<<s.query_us<<','<<s.route_us<<','<<s.pq_us<<','<<s.rerank_us<<','<<s.candidates<<','<<s.reranked<<','<<s.ios<<','<<skips[q]<<','<<tunnel[q]<<','<<s.enumerated<<','<<phase_us<<','<<build_us<<','<<postings.bytes()<<'\n';
  }
  std::ofstream ids(argv[9],std::ios::binary); uint32_t result_hdr[2]={uint32_t(nq),uint32_t(k)};
  ids.write(reinterpret_cast<char*>(result_hdr),8);
  ids.write(reinterpret_cast<char*>(results.data()),results.size()*4);
  if(!out || !ids) throw std::runtime_error("Output write failed");
  std::cout<<"COMPLETE policy="<<policy<<" nq="<<nq<<" mean_phase_us="<<phase_us/nq<<std::endl;
  return 0;
 } catch(const std::exception &e) { std::cerr<<"ERROR: "<<e.what()<<std::endl; return 1; }
}
