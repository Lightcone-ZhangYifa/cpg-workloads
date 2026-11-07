import runpy,sys
sys.path.append(sys.argv.pop(1))
sys.argv.pop(0)
runpy.run_module("pip",run_name="__main__")
