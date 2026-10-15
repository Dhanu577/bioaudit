#include <thread>
#include <vector>
#define PACK_SIZE 256
struct Options { int thread = 1; int qualified_quality_phred = 20; };
void run(Options& o) { std::vector<std::thread> pool; for (int i = 0; i < o.thread; i++) {} }
