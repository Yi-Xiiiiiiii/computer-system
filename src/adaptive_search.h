#pragma once
// Student extension: CSR label inversion + selectivity router + PQ shortlist.
// Course scope: static uint8/L2 indices with identity ID/tag/page mappings.
#include "ssd_index.h"
#include <filesystem>
#include <numeric>

namespace adaptive {
using Clock = std::chrono::steady_clock;
inline double us(Clock::time_point start) {
  return std::chrono::duration<double, std::micro>(Clock::now() - start).count();
}

template<class T> void read_exact(std::ifstream &in, T *out, size_t count) {
  if (count && !in.read(reinterpret_cast<char *>(out), count * sizeof(T)))
    throw std::runtime_error("Truncated binary input");
}

// Only O(number of labels + number of postings) retained after construction.
// Zero-valued CSR entries are absent; duplicate labels in a row are deduplicated.
class LabelPostings {
 public:
  uint32_t nodes = 0;
  std::vector<uint64_t> offsets;
  std::vector<uint32_t> ids;

  void load(const std::string &path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot open metadata: " + path);
    int64_t shape[3];
    read_exact(in, shape, 3);
    auto [nr, nc, nz] = std::tuple<int64_t,int64_t,int64_t>{shape[0],shape[1],shape[2]};
    if (nr < 0 || nr > UINT32_MAX || nc < 0 || nc > UINT32_MAX || nz < 0)
      throw std::runtime_error("Invalid CSR shape");
    const uint64_t expected = 24 + (uint64_t(nr) + 1) * 8 + uint64_t(nz) * 8;
    if (std::filesystem::file_size(path) != expected)
      throw std::runtime_error("Invalid CSR file size");
    std::vector<int64_t> ptr(nr + 1);
    std::vector<int32_t> labels(nz);
    std::vector<float> values(nz);
    read_exact(in, ptr.data(), ptr.size());
    read_exact(in, labels.data(), labels.size());
    read_exact(in, values.data(), values.size());
    if (ptr.front() != 0 || ptr.back() != nz || !std::is_sorted(ptr.begin(), ptr.end()))
      throw std::runtime_error("Invalid CSR offsets");
    nodes = nr;
    offsets.assign(nc + 1, 0);
    std::vector<int64_t> seen(nc, -1);
    for (int64_t row = 0; row < nr; ++row)
      for (int64_t j = ptr[row]; j < ptr[row+1]; ++j) {
        if (labels[j] < 0 || labels[j] >= nc) throw std::runtime_error("Invalid label ID");
        if (values[j] != 0 && seen[labels[j]] != row) {
          ++offsets[labels[j]+1]; seen[labels[j]] = row;
        }
      }
    std::partial_sum(offsets.begin(), offsets.end(), offsets.begin());
    ids.resize(offsets.back());
    auto cursor = offsets;
    std::fill(seen.begin(), seen.end(), -1);
    for (int64_t row = 0; row < nr; ++row)
      for (int64_t j = ptr[row]; j < ptr[row+1]; ++j)
        if (values[j] != 0 && seen[labels[j]] != row) {
          ids[cursor[labels[j]]++] = row; seen[labels[j]] = row;
        }
  }
  size_t count(uint32_t label) const {
    return uint64_t(label)+1 < offsets.size() ? offsets[label+1]-offsets[label] : 0;
  }
  const uint32_t *begin(uint32_t label) const {
    return count(label) ? ids.data() + offsets[label] : nullptr;
  }
  uint64_t bytes() const { return offsets.capacity()*8 + ids.capacity()*4; }
};

struct Metrics {
  double route_us=0, pq_us=0, rerank_us=0, query_us=0;
  uint64_t candidates=0, ios=0, reranked=0;
  bool enumerated=false;
};

inline bool should_enumerate(size_t count, size_t nodes, double threshold) {
  return nodes > 0 && double(count)/double(nodes) < threshold;
}

// Explicitly reject reordered / remapped indices instead of silently reading
// the wrong vector. The supplied course formal/debug indices use identity IDs.
inline void check_identity_layout(const std::string &prefix) {
  for (const auto &suffix : {"_partition.bin.aligned", "_disk.index.tags"})
    if (std::filesystem::exists(prefix + suffix))
      throw std::runtime_error("Adaptive path requires course identity layout: " + prefix + suffix);
}

inline void search(pipeann::SSDIndex<uint8_t> &index,
                   pipeann::AbstractNeighbor<uint8_t> &pq,
                   AlignedFileReader &reader, const LabelPostings &postings,
                   const uint8_t *query, uint32_t label, size_t k, size_t m,
                   uint32_t beamwidth, uint32_t *output, Metrics &stats) {
  if (k == 0 || m < k || beamwidth == 0 || beamwidth > MAX_N_SECTOR_READS)
    throw std::runtime_error("Require 0<K<=M and 0<beamwidth<=128");
  const size_t count = postings.count(label);
  stats.enumerated = true;
  stats.candidates = count;
  std::fill(output, output+k, UINT32_MAX);
  if (!count) return;
  auto *buf = index.pop_query_buf(query);
  struct ReturnBuffer {
    pipeann::SSDIndex<uint8_t> &idx; pipeann::QueryBuffer<uint8_t> *buf;
    ~ReturnBuffer() { idx.push_query_buf(buf); }
  } guard{index,buf};
  const auto pq_start = Clock::now();
  pq.initialize_query(buf->aligned_query_T, buf);
  std::vector<std::pair<float,uint32_t>> ranked;
  ranked.reserve(count);
  const auto *ids = postings.begin(label);
  // GateANN query scratch has MAX_N_EDGES slots: never overflow it.
  for (size_t off=0; off<count; off+=MAX_N_EDGES) {
    size_t batch = std::min(count-off, MAX_N_EDGES);
    pq.compute_dists(buf, ids+off, batch);
    for (size_t j=0; j<batch; ++j)
      ranked.emplace_back(buf->aligned_dist_scratch[j],ids[off+j]);
  }
  m = std::min(m,count);
  std::partial_sort(ranked.begin(),ranked.begin()+m,ranked.end());
  ranked.resize(m);
  stats.pq_us = us(pq_start);
  const auto rerank_start = Clock::now();
  const size_t page_bytes = SECTOR_LEN * (index.meta_.nnodes_per_sector ? 1 :
      DIV_ROUND_UP(index.meta_.max_node_len,SECTOR_LEN));
  std::vector<std::pair<float,uint32_t>> exact;
  exact.reserve(m);
  void *ctx = reader.get_ctx();
  for (size_t off=0; off<m; off+=beamwidth) {
    const size_t batch = std::min(m-off,size_t(beamwidth));
    std::vector<IORequest> requests;
    requests.reserve(batch);
    for (size_t j=0; j<batch; ++j) {
      const uint32_t id = ranked[off+j].second;  // checked identity mapping
      char *page = buf->sector_scratch + j*page_bytes;
      requests.emplace_back(index.loc_sector_no(id)*SECTOR_LEN,page_bytes,page,
                            index.u_loc_offset(id),index.meta_.max_node_len,page);
    }
    reader.read(requests,ctx,false); // libaio, batched and awaited
    for (size_t j=0; j<batch; ++j) {
      const uint32_t id = ranked[off+j].second;
      auto node = index.node_from_page(buf->sector_scratch+j*page_bytes,id);
      // uint8 L2 is accumulated without overflow or approximate PQ distances.
      float distance=0;
      for (size_t d=0; d<index.meta_.data_dim; ++d) {
        int delta=int(query[d])-int(node.coords[d]); distance+=delta*delta;
      }
      exact.emplace_back(distance,id);
    }
    stats.ios += batch;
  }
  const size_t out_count=std::min(k,exact.size());
  std::partial_sort(exact.begin(),exact.begin()+out_count,exact.end());
  for (size_t i=0; i<out_count; ++i) output[i]=exact[i].second;
  stats.reranked=m;
  stats.rerank_us=us(rerank_start);
}
} // namespace adaptive
