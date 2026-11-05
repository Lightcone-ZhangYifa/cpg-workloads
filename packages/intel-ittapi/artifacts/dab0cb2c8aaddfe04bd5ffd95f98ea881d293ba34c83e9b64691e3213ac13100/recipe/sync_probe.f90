program sync_probe
  use iso_c_binding, only: C_INTPTR_T
  use ittnotify
  implicit none
  call itt_sync_create(int(z'12345678abcdef01',C_INTPTR_T), 'cpg-sync', itt_attr_mutex)
end program sync_probe
