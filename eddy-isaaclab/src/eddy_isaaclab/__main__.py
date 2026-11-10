"""`python -m eddy_isaaclab --url <engine>`: the hook's self-test (no Isaac needed; numpy needed)."""
import argparse
import os

from .audit import selftest


def main():
    ap = argparse.ArgumentParser(prog="python -m eddy_isaaclab")
    ap.add_argument("--url", default=os.environ.get("SS_URL", "http://127.0.0.1:8080"))
    ap.add_argument("--envs", type=int, default=4096)
    ap.add_argument("--every", type=int, default=512, help="audit every Nth env (512: 8 audits)")
    args = ap.parse_args()
    selftest(args.url, envs=args.envs, every=args.every)


if __name__ == "__main__":
    main()
