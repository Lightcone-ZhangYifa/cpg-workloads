program papi_consumer
  implicit none
  include 'f90papi.h'
  integer :: status, eventset
  status = PAPI_VER_CURRENT
  call PAPIF_library_init(status)
  if (status /= PAPI_VER_CURRENT) stop 1
  eventset = PAPI_NULL
  call PAPIF_create_eventset(eventset, status)
  if (status /= PAPI_OK) stop 2
  call PAPIF_destroy_eventset(eventset, status)
  if (status /= PAPI_OK .or. eventset /= PAPI_NULL) stop 3
  call PAPIF_shutdown()
  print *, 'PAPI Fortran initialization/eventset lifecycle passed'
end program papi_consumer
