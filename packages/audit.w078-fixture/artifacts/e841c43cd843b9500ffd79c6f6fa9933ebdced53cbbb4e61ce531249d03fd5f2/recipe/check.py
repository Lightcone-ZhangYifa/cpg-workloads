import pathlib,sys
assert (pathlib.Path(sys.argv[1])/'note.txt').is_file()
print('audit fixture available')
