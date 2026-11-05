-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA512

Format: 3.0 (quilt)
Source: elfutils
Binary: elfutils, libelf1t64, libelf-dev, libdw-dev, libdw1t64, libasm1t64, libasm-dev, libdebuginfod1t64, libdebuginfod-dev, debuginfod, libdebuginfod-common
Architecture: any all
Version: 0.190-1.1ubuntu0.1
Maintainer: Ubuntu Developers <ubuntu-devel-discuss@lists.ubuntu.com>
Uploaders: Kurt Roeckx <kurt@roeckx.be>, Matthias Klose <doko@debian.org>, Sergio Durigan Junior <sergiodj@debian.org>,
Homepage: https://sourceware.org/elfutils/
Standards-Version: 4.6.2
Vcs-Browser: https://salsa.debian.org/toolchain-team/elfutils
Vcs-Git: https://salsa.debian.org/toolchain-team/elfutils.git
Build-Depends: dpkg-dev (>= 1.22.5), debhelper (>= 11), autoconf, automake, lsb-release, bzip2, zlib1g-dev, zlib1g-dev:native, libbz2-dev, liblzma-dev, libzstd-dev, zstd <!nocheck>, m4, gettext, po-debconf, gawk, gcc-multilib [any-amd64 sparc64] <!nocheck>, libc6-dbg [powerpc powerpcspe ppc64 ppc64el armel armhf arm64 sparc64 riscv64], flex, bison, pkg-config, libarchive-dev <!pkg.elfutils.nodebuginfod>, libmicrohttpd-dev <!pkg.elfutils.nodebuginfod>, libcurl4-gnutls-dev <!pkg.elfutils.nodebuginfod>, libsqlite3-dev <!pkg.elfutils.nodebuginfod>
Build-Conflicts: autoconf2.13
Package-List:
 debuginfod deb devel optional arch=any profile=!pkg.elfutils.nodebuginfod
 elfutils deb utils optional arch=any
 libasm-dev deb libdevel optional arch=any
 libasm1t64 deb libs optional arch=any
 libdebuginfod-common deb devel optional arch=all profile=!pkg.elfutils.nodebuginfod
 libdebuginfod-dev deb libdevel optional arch=any profile=!pkg.elfutils.nodebuginfod
 libdebuginfod1t64 deb libs optional arch=any profile=!pkg.elfutils.nodebuginfod
 libdw-dev deb libdevel optional arch=any
 libdw1t64 deb libs optional arch=any
 libelf-dev deb libdevel optional arch=any
 libelf1t64 deb libs optional arch=any
Checksums-Sha1:
 b33fdb927bc154f6ca6285194d0e40fb76877dd0 9162766 elfutils_0.190.orig.tar.bz2
 e299bb80e7dbbb56fcaf904e0d6c0f4b3e04189b 46976 elfutils_0.190-1.1ubuntu0.1.debian.tar.xz
Checksums-Sha256:
 8e00a3a9b5f04bc1dc273ae86281d2d26ed412020b391ffcc23198f10231d692 9162766 elfutils_0.190.orig.tar.bz2
 4c3130951f7b865d50ff57379a258926a66bcd2753e3c12301bbb110fbb417fa 46976 elfutils_0.190-1.1ubuntu0.1.debian.tar.xz
Files:
 79ad698e61a052bea79e77df6a08bc4b 9162766 elfutils_0.190.orig.tar.bz2
 cf486f585622b3219daa305dc81681fb 46976 elfutils_0.190-1.1ubuntu0.1.debian.tar.xz
Original-Maintainer: Debian Elfutils Maintainers <debian-gcc@lists.debian.org>

-----BEGIN PGP SIGNATURE-----

iQJRBAEBCgA7FiEE2WgtvmwmcgaEBLlnCAvK1QvD6SAFAmfYS20dHGZhYmlhbi50
b2VwZmVyQGNhbm9uaWNhbC5jb20ACgkQCAvK1QvD6SB60RAAv/rGCl7chEpWKj2H
lH1z+mbkaGuMKV54awRvGfdiXERSluPt1d8eWOxgAByp/Z+61yFqxuOAa215bGc7
gV7cY99HLxjugURVJxrOTnpCATrh/ustDMkAbI3rmp2bbPSg4Nn8pyqTAukeYj0Y
V1onYo3gP0PcaiCMjAmVDb39+jC8n34W2i26fHZnxAbVkDoeQMcugyOnMar2T31l
lPOi5T8xAvzG/c9fCNSFB+3q6oT7Jh4iwW0al5wbjj81FEILblnzr4d4hWMSAa1D
AJ1fNP7pn9h2ggUbyO61KYlIOQK1+Nwtm059E2rnf5eTmnXP3JGfB3V5Cdd/sRWE
uHFhFtdgGeK5Yw7ah2P0Accx86PkNPfSCb4gF0MUoaWoYaFAvzfoxZLg5GTu5CsP
4H9WiyXWi4edt/bDsUy78wG1VX8lTmOk7y+o2TWQPO6t7cZiHP2SZEJSOjyxF5rD
hoCsLIU4Vu73EUZ7+5NEduM0iODzqL7LTp2WhPG5s6IAnyvWX6tfhTAjhhtkE7fp
26PExYVrauCNQidPou9gy6ZSasCkIoygrdilIY/rO0bZAyk06ktxoTDGHOX3qMji
2CDhGcTYye1T9jsbZhWdfbN66PAaivueYBSwV2T3CSNX0mO59wPQaCiCK8LPsPVW
eghqFP2sknFSlIbzWrLvcQLww6Q=
=sjC1
-----END PGP SIGNATURE-----
