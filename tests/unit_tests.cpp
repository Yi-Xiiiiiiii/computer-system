#include "adaptive_search.h"
#include <iostream>

void require(bool condition,const char *message) {
  if (!condition) throw std::runtime_error(message);
}
template<class T> void write(std::ofstream &out,const std::vector<T> &v) {
  out.write(reinterpret_cast<const char*>(v.data()),v.size()*sizeof(T));
}
int main(int argc,char **argv) {
 try {
  if(argc!=2) throw std::runtime_error("Usage: unit_tests TEMP_FILE");
  {
    std::ofstream out(argv[1],std::ios::binary);
    write<int64_t>(out,{3,4,6}); write<int64_t>(out,{0,3,4,6});
    write<int32_t>(out,{1,1,2,0,1,3}); write<float>(out,{1,1,0,1,1,1});
  }
  adaptive::LabelPostings p; p.load(argv[1]);
  require(p.nodes==3,"CSR rows");
  require(p.count(1)==2 && p.begin(1)[0]==0 && p.begin(1)[1]==2,"Deduplication / postings IDs");
  require(p.count(2)==0,"Zero valued entry is absent");
  require(p.count(0)==1 && p.count(3)==1,"Last label boundary");
  require(p.count(UINT32_MAX)==0 && p.begin(UINT32_MAX)==nullptr,"Unknown label handling");
  require(!adaptive::should_enumerate(1,100,.01),"Threshold uses strict <");
  require(adaptive::should_enumerate(0,100,.01),"Empty label routed to empty result");
  require(!adaptive::should_enumerate(0,100,0),"Threshold zero disables enumeration");
  require(!adaptive::should_enumerate(0,0,.01),"Zero base cardinality");
  {
    std::ofstream out(argv[1],std::ios::binary); write<int64_t>(out,{3,4,6});
  }
  bool rejected=false;
  try { adaptive::LabelPostings bad; bad.load(argv[1]); } catch(const std::exception&) { rejected=true; }
  require(rejected,"Truncated input must be rejected");
  std::cout<<"PASS: CSR inversion, duplicate/zero entries, unknown labels, route boundaries, truncated input\n";
  return 0;
 } catch(const std::exception &e) { std::cerr<<"FAIL: "<<e.what()<<'\n'; return 1; }
}
