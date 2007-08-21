import re,sys
# strips blank lines
m = re.compile(r'^\s*$')
fname = sys.argv[1]
fd = open(fname,mode='r')
for line in fd:
    mo = m.search(line)
    if mo is None:
        print line.rstrip()
    
