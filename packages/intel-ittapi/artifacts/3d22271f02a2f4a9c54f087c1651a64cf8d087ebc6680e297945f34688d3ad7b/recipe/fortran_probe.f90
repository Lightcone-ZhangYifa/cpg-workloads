program fortran_probe
  use ittnotify
  implicit none
  call itt_thread_set_name('cpg-fortran-worker')
  call itt_pause()
  call itt_resume()
  print *, 'Fortran ITT calls completed; collector traces must be checked separately.'
end program fortran_probe
