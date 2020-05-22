from marcel.api import *
import time

# cat = map(lambda f: (f, f.readlines())) | expand(1)
# for f, line in ls('/home/jao/*.txt', file=True, recursive=True) | cat:
#     print(f'{f}: {line}')

# run(remote('jao', gen(3)))

# for ext, count, size in (ls('/home/jao/git/marcel', file=True, recursive=True)
#                          | map(lambda f: (f.suffix.lower(), 1, f.size))
#                          | red(None, r_plus, r_plus)
#                          | sort(lambda ext, count, size: -size)
#                          | head(10)):
#     print(f'{ext}: {size / count}')
#
# for size, pid, commandline in (ps(command='python')
#                                | sort(lambda p: p.VmRSS)
#                                | map(lambda p: (p.VmRSS, p.pid, p.commandline))):
#     print(f'{size} -- {pid}: {commandline}')

# For profiling
N = 1000000
start = time.time()
run(gen(N) | map(lambda x: x+1) | map(lambda x: x+1) | map(lambda x: x+1) | select(lambda x: False))
stop = time.time()
usec = (stop - start) * 1000000 / N
print(f'{usec} usec per unit')
