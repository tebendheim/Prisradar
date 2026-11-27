"""Single entrypoint for store-discovery.yml: one clock for the whole job, each step isolated."""
import time
JOB_SECONDS=270   # timeout is 360 s; checkout, setup and tests use ~30 s before Python starts

def step(name,fn):
    try:return fn()
    except Exception as e:
        print("Step",name,"failed:",type(e).__name__,str(e)[:160],flush=True);return None

def main(start=None,budget=JOB_SECONDS):
    import brreg_seed,store_adapters
    start=time.monotonic() if start is None else start;deadline=start+budget
    step("brreg",lambda:brreg_seed.run(deadline=start+90))
    step("curated",brreg_seed.seed_curated)
    step("links",lambda:brreg_seed.seed_from_active(deadline=start+130))
    step("probe",lambda:store_adapters.probe_candidates(deadline))

if __name__=="__main__":main()
