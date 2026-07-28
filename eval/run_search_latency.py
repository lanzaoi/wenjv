import asyncio
import time
from backend.api.services.search import search_documents
from backend.config import settings

async def run_baseline():
    # Force timing on for this script
    settings.SEARCH_TIMING_ENABLED = True
    settings.HYBRID_SEARCH_ENABLED = True # force hybrid for legs
    
    prompt = "测试查询：什么是向量检索？"
    user_email = "test@example.com"
    n_runs = 5
    
    print(f"=== Search Latency Baseline ===")
    print(f"Query: '{prompt}'")
    print(f"Runs: {n_runs}")
    print("-" * 40)
    
    for parallel in [False, True]:
        settings.SEARCH_PARALLEL_LEGS = parallel
        print(f"\n[Mode: Parallel={parallel}]")
        
        # Warmup
        print("Warming up (1 run)...")
        try:
            await search_documents(prompt=prompt, user_email=user_email)
        except Exception as e:
            print(f"Warmup failed: {e}")
            
        print("-" * 40)
        
        total_times = []
        
        for i in range(1, n_runs + 1):
            t0 = time.perf_counter()
            await search_documents(prompt=prompt, user_email=user_email)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            total_times.append(elapsed_ms)
            print(f"Run {i}: {elapsed_ms:.2f} ms")
            
        avg_time = sum(total_times) / len(total_times)
        print("-" * 40)
        print(f"Average Total Latency: {avg_time:.2f} ms")
        print(f"Note: Check the application logs for detailed phase timings (search_timings: {{...}})")

if __name__ == "__main__":
    asyncio.run(run_baseline())
