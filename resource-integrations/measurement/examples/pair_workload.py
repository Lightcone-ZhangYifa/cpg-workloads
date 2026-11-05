"""Small correctness/scheduling demonstration, not a resource benchmark score."""
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("variant", choices=["baseline", "candidate"])
parser.add_argument("n", type=int)
args = parser.parse_args()
if args.n < 1:
    raise SystemExit("n must be positive")
if args.variant == "baseline":
    value = 0
    for i in range(args.n):
        value += i * i
else:
    value = sum(i * i for i in range(args.n))
expected = (args.n - 1) * args.n * (2 * args.n - 1) // 6
if value != expected:
    raise SystemExit("incorrect sum of squares")
print(value)
