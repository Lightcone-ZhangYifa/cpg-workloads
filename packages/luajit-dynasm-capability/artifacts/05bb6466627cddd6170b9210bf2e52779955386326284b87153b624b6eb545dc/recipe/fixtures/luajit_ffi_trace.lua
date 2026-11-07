local ffi=require('ffi')
ffi.cdef[[void qsort(void *base, size_t nmemb, size_t size, int (*compar)(const void *, const void *));]]
local a=ffi.new('int[8]', {7,-4,0,99,3,-11,8,1})
local calls=0
local cb=ffi.cast('int(*)(const void*,const void*)',function(x,y)
  calls=calls+1
  local ax=ffi.cast('const int*',x)[0]
  local ay=ffi.cast('const int*',y)[0]
  return ax<ay and -1 or (ax>ay and 1 or 0)
end)
ffi.C.qsort(a,8,ffi.sizeof('int'),cb)
local expected={-11,-4,0,1,3,7,8,99}
for i=0,7 do assert(a[i]==expected[i+1]) end
cb:free()
assert(calls>0)
print('LUAJIT_FFI_PASS qsort_values=8 callback_calls='..calls)
local jit=require('jit')
local util=require('jit.util')
jit.flush()
jit.opt.start('hotloop=1','hotexit=1')
local function sum(n)local a=0;for i=1,n do a=a+i end;return a end
for k=1,20 do assert(sum(10000)==50005000) end
local traces=0
for i=1,128 do local info=util.traceinfo(i);if info and info.nins>0 then traces=traces+1 end end
assert(traces>0,'no JIT trace was recorded')
print('LUAJIT_TRACE_PASS traces='..traces..' repeated_sum=50005000')
