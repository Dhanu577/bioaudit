#include <thread>
#include <vector>
#define PACK_SIZE 1000
struct Options { int thread = 3; int qualified_quality_phred = 15; };
void run(Options& o) { std::vector<std::thread> pool; for (int i = 0; i < o.thread; i++) {} }
