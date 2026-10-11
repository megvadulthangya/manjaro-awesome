# Mpatch Debug Report

> **Note:** This report has been partially anonymized. Please review for any remaining sensitive information before sharing.

- **Mpatch Version:** `1.6.4`
- **OS:** `linux`
- **Architecture:** `x86_64`
- **Timestamp (Unix):** `1791718249`

## Command Line

```sh
mpatch -vvvv <INPUT_FILE> <TARGET_DIR>
```

## Input Patch File

````markdown
--- a/libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc
+++ b/libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc
@@ -153,7 +153,6 @@
 #include <linux/cyclades.h>
 #include <linux/if_eql.h>
 #include <linux/if_plip.h>
-#include <linux/scc.h>
 #include <linux/serial.h>
 #include <linux/sockios.h>
 #include <linux/termios.h>
@@ -400,7 +399,6 @@
   unsigned struct_input_id_sz = sizeof(struct input_id);
   unsigned struct_mtpos_sz = sizeof(struct mtpos);
   unsigned struct_rtentry_sz = sizeof(struct rtentry);
-  unsigned struct_scc_sz = sizeof(struct scc);
   unsigned struct_termio_sz = sizeof(struct termio);
   unsigned struct_vt_consize_sz = sizeof(struct vt_consize);
   unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);
````

## Original Target File(s)

### File: `libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc`

````cc
//===-- sanitizer_platform_limits_posix.cc --------------------------------===//
//
// This file is distributed under the University of Illinois Open Source
// License. See LICENSE.TXT for details.
//
//===----------------------------------------------------------------------===//
//
// This file is a part of Sanitizer common code.
//
// Sizes and layouts of platform-specific POSIX data structures.
//===----------------------------------------------------------------------===//

#include "sanitizer_platform.h"

#if SANITIZER_LINUX || SANITIZER_FREEBSD || SANITIZER_MAC
// Tests in this file assume that off_t-dependent data structures match the
// libc ABI. For example, struct dirent here is what readdir() function (as
// exported from libc) returns, and not the user-facing "dirent", which
// depends on _FILE_OFFSET_BITS setting.
// To get this "true" dirent definition, we undefine _FILE_OFFSET_BITS below.
#ifdef _FILE_OFFSET_BITS
#undef _FILE_OFFSET_BITS
#endif
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <grp.h>
#include <limits.h>
#include <net/if.h>
#include <netdb.h>
#include <poll.h>
#include <pthread.h>
#include <pwd.h>
#include <signal.h>
#include <stddef.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/times.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <termios.h>
#include <time.h>
#include <wchar.h>

#if !SANITIZER_IOS
#include <net/route.h>
#endif

#if !SANITIZER_ANDROID
#include <sys/mount.h>
#include <sys/timeb.h>
#endif

#if SANITIZER_LINUX
#include <malloc.h>
#include <mntent.h>
#include <netinet/ether.h>
#include <sys/sysinfo.h>
#include <sys/vt.h>
#include <linux/cdrom.h>
#include <linux/fd.h>
#include <linux/fs.h>
#include <linux/hdreg.h>
#include <linux/input.h>
#include <linux/ioctl.h>
#include <linux/soundcard.h>
#include <linux/sysctl.h>
#include <linux/utsname.h>
#include <linux/posix_types.h>
#include <net/if_arp.h>
#endif

#if SANITIZER_FREEBSD
# include <sys/mount.h>
# include <sys/sockio.h>
# include <sys/socket.h>
# include <sys/filio.h>
# include <sys/signal.h>
# include <sys/timespec.h>
# include <sys/timex.h>
# include <sys/mqueue.h>
# include <sys/msg.h>
# include <sys/ipc.h>
# include <sys/msg.h>
# include <sys/statvfs.h>
# include <sys/soundcard.h>
# include <sys/mtio.h>
# include <sys/consio.h>
# include <sys/kbio.h>
# include <sys/link_elf.h>
# include <netinet/ip_mroute.h>
# include <netinet/in.h>
# include <net/ethernet.h>
# include <net/ppp_defs.h>
# include <glob.h>
# include <term.h>

#define _KERNEL  // to declare 'shminfo' structure
# include <sys/shm.h>
#undef _KERNEL

#undef INLINE  // to avoid clashes with sanitizers' definitions
#endif

#if SANITIZER_FREEBSD || SANITIZER_IOS
#undef IOC_DIRMASK
#endif

#if SANITIZER_LINUX || SANITIZER_FREEBSD
# include <utime.h>
# include <sys/ptrace.h>
# if defined(__mips64) || defined(__aarch64__) || defined(__arm__)
#  include <asm/ptrace.h>
#  ifdef __arm__
typedef struct user_fpregs elf_fpregset_t;
#  endif
# endif
# include <semaphore.h>
#endif

#if !SANITIZER_ANDROID
#include <ifaddrs.h>
#include <sys/ucontext.h>
#include <wordexp.h>
#endif

#if SANITIZER_LINUX && !SANITIZER_ANDROID
#include <glob.h>
#include <obstack.h>
#include <mqueue.h>
#include <net/if_ppp.h>
#include <netax25/ax25.h>
#include <netipx/ipx.h>
#include <netrom/netrom.h>
#if HAVE_RPC_XDR_H
# include <rpc/xdr.h>
#elif HAVE_TIRPC_RPC_XDR_H
# include <tirpc/rpc/xdr.h>
#endif
#include <scsi/scsi.h>
#include <sys/mtio.h>
#include <sys/kd.h>
#include <sys/shm.h>
#include <sys/statvfs.h>
#include <sys/timex.h>
#if defined(__mips64)
# include <sys/procfs.h>
#endif
#include <sys/user.h>
#include <linux/cyclades.h>
#include <linux/if_eql.h>
#include <linux/if_plip.h>
#include <linux/lp.h>
#include <linux/mroute.h>
#include <linux/mroute6.h>
#include <linux/scc.h>
#include <linux/serial.h>
#include <sys/msg.h>
#include <sys/ipc.h>
#endif // SANITIZER_LINUX && !SANITIZER_ANDROID

#if SANITIZER_ANDROID
#include <linux/kd.h>
#include <linux/mtio.h>
#include <linux/ppp_defs.h>
#include <linux/if_ppp.h>
#endif

#if SANITIZER_LINUX
#include <link.h>
#include <sys/vfs.h>
#include <sys/epoll.h>
#include <linux/capability.h>
#endif // SANITIZER_LINUX

#if SANITIZER_MAC
#include <net/ethernet.h>
#include <sys/filio.h>
#include <sys/sockio.h>
#endif

// Include these after system headers to avoid name clashes and ambiguities.
#include "sanitizer_internal_defs.h"
#include "sanitizer_platform_limits_posix.h"

namespace __sanitizer {
  unsigned struct_utsname_sz = sizeof(struct utsname);
  unsigned struct_stat_sz = sizeof(struct stat);
#if !SANITIZER_IOS && !SANITIZER_FREEBSD
  unsigned struct_stat64_sz = sizeof(struct stat64);
#endif // !SANITIZER_IOS && !SANITIZER_FREEBSD
  unsigned struct_rusage_sz = sizeof(struct rusage);
  unsigned struct_tm_sz = sizeof(struct tm);
  unsigned struct_passwd_sz = sizeof(struct passwd);
  unsigned struct_group_sz = sizeof(struct group);
  unsigned siginfo_t_sz = sizeof(siginfo_t);
  unsigned struct_sigaction_sz = sizeof(struct sigaction);
  unsigned struct_itimerval_sz = sizeof(struct itimerval);
  unsigned pthread_t_sz = sizeof(pthread_t);
  unsigned pthread_cond_t_sz = sizeof(pthread_cond_t);
  unsigned pid_t_sz = sizeof(pid_t);
  unsigned timeval_sz = sizeof(timeval);
  unsigned uid_t_sz = sizeof(uid_t);
  unsigned gid_t_sz = sizeof(gid_t);
  unsigned mbstate_t_sz = sizeof(mbstate_t);
  unsigned sigset_t_sz = sizeof(sigset_t);
  unsigned struct_timezone_sz = sizeof(struct timezone);
  unsigned struct_tms_sz = sizeof(struct tms);
  unsigned struct_sigevent_sz = sizeof(struct sigevent);
  unsigned struct_sched_param_sz = sizeof(struct sched_param);


#if SANITIZER_MAC && !SANITIZER_IOS
  unsigned struct_statfs64_sz = sizeof(struct statfs64);
#endif // SANITIZER_MAC && !SANITIZER_IOS

#if !SANITIZER_ANDROID
  unsigned struct_statfs_sz = sizeof(struct statfs);
  unsigned struct_sockaddr_sz = sizeof(struct sockaddr);
  unsigned ucontext_t_sz = sizeof(ucontext_t);
#endif // !SANITIZER_ANDROID

#if SANITIZER_LINUX
  unsigned struct_epoll_event_sz = sizeof(struct epoll_event);
  unsigned struct_sysinfo_sz = sizeof(struct sysinfo);
  unsigned __user_cap_header_struct_sz =
      sizeof(struct __user_cap_header_struct);
  unsigned __user_cap_data_struct_sz = sizeof(struct __user_cap_data_struct);
  unsigned struct_new_utsname_sz = sizeof(struct new_utsname);
  unsigned struct_old_utsname_sz = sizeof(struct old_utsname);
  unsigned struct_oldold_utsname_sz = sizeof(struct oldold_utsname);
#endif // SANITIZER_LINUX

#if SANITIZER_LINUX || SANITIZER_FREEBSD
  unsigned struct_rlimit_sz = sizeof(struct rlimit);
  unsigned struct_timespec_sz = sizeof(struct timespec);
  unsigned struct_utimbuf_sz = sizeof(struct utimbuf);
  unsigned struct_itimerspec_sz = sizeof(struct itimerspec);
#endif // SANITIZER_LINUX || SANITIZER_FREEBSD

#if SANITIZER_LINUX && !SANITIZER_ANDROID
  // Use pre-computed size of struct ustat to avoid <sys/ustat.h> which
  // has been removed from glibc 2.28.
#if defined(__aarch64__) || defined(__s390x__) || defined (__mips64) \
  || defined(__powerpc64__) || defined(__arch64__) || defined(__sparcv9) \
  || defined(__x86_64__)
#define SIZEOF_STRUCT_USTAT 32
#elif defined(__arm__) || defined(__i386__) || defined(__mips__) \
  || defined(__powerpc__) || defined(__s390__) || defined(__sparc__)
#define SIZEOF_STRUCT_USTAT 20
#else
#error Unknown size of struct ustat
#endif
  unsigned struct_ustat_sz = SIZEOF_STRUCT_USTAT;
  unsigned struct_rlimit64_sz = sizeof(struct rlimit64);
  unsigned struct_statvfs64_sz = sizeof(struct statvfs64);
#endif // SANITIZER_LINUX && !SANITIZER_ANDROID

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
  unsigned struct_timex_sz = sizeof(struct timex);
  unsigned struct_msqid_ds_sz = sizeof(struct msqid_ds);
  unsigned struct_mq_attr_sz = sizeof(struct mq_attr);
  unsigned struct_statvfs_sz = sizeof(struct statvfs);
#endif // (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID

  uptr sig_ign = (uptr)SIG_IGN;
  uptr sig_dfl = (uptr)SIG_DFL;
  uptr sa_siginfo = (uptr)SA_SIGINFO;

#if SANITIZER_LINUX
  int e_tabsz = (int)E_TABSZ;
#endif


#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
  unsigned struct_shminfo_sz = sizeof(struct shminfo);
  unsigned struct_shm_info_sz = sizeof(struct shm_info);
  int shmctl_ipc_stat = (int)IPC_STAT;
  int shmctl_ipc_info = (int)IPC_INFO;
  int shmctl_shm_info = (int)SHM_INFO;
  int shmctl_shm_stat = (int)SHM_STAT;
#endif

  int map_fixed = MAP_FIXED;

  int af_inet = (int)AF_INET;
  int af_inet6 = (int)AF_INET6;

  uptr __sanitizer_in_addr_sz(int af) {
    if (af == AF_INET)
      return sizeof(struct in_addr);
    else if (af == AF_INET6)
      return sizeof(struct in6_addr);
    else
      return 0;
  }

#if SANITIZER_LINUX
unsigned struct_ElfW_Phdr_sz = sizeof(ElfW(Phdr));
#elif SANITIZER_FREEBSD
unsigned struct_ElfW_Phdr_sz = sizeof(Elf_Phdr);
#endif

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
  int glob_nomatch = GLOB_NOMATCH;
  int glob_altdirfunc = GLOB_ALTDIRFUNC;
#endif

#if SANITIZER_LINUX && !SANITIZER_ANDROID && \
    (defined(__i386) || defined(__x86_64) || defined(__mips64) || \
      defined(__powerpc64__) || defined(__aarch64__) || defined(__arm__))
#if defined(__mips64) || defined(__powerpc64__) || defined(__arm__)
  unsigned struct_user_regs_struct_sz = sizeof(struct pt_regs);
  unsigned struct_user_fpregs_struct_sz = sizeof(elf_fpregset_t);
#elif defined(__aarch64__)
  unsigned struct_user_regs_struct_sz = sizeof(struct user_pt_regs);
  unsigned struct_user_fpregs_struct_sz = sizeof(struct user_fpsimd_state);
#else
  unsigned struct_user_regs_struct_sz = sizeof(struct user_regs_struct);
  unsigned struct_user_fpregs_struct_sz = sizeof(struct user_fpregs_struct);
#endif // __mips64 || __powerpc64__ || __aarch64__
#if defined(__x86_64) || defined(__mips64) || defined(__powerpc64__) || \
    defined(__aarch64__) || defined(__arm__)
  unsigned struct_user_fpxregs_struct_sz = 0;
#else
  unsigned struct_user_fpxregs_struct_sz = sizeof(struct user_fpxregs_struct);
#endif // __x86_64 || __mips64 || __powerpc64__ || __aarch64__ || __arm__
#ifdef __arm__
  unsigned struct_user_vfpregs_struct_sz = ARM_VFPREGS_SIZE;
#else
  unsigned struct_user_vfpregs_struct_sz = 0;
#endif

  int ptrace_peektext = PTRACE_PEEKTEXT;
  int ptrace_peekdata = PTRACE_PEEKDATA;
  int ptrace_peekuser = PTRACE_PEEKUSER;
#if (defined(PTRACE_GETREGS) && defined(PTRACE_SETREGS)) || \
    (defined(PT_GETREGS) && defined(PT_SETREGS))
  int ptrace_getregs = PTRACE_GETREGS;
  int ptrace_setregs = PTRACE_SETREGS;
#else
  int ptrace_getregs = -1;
  int ptrace_setregs = -1;
#endif
#if (defined(PTRACE_GETFPREGS) && defined(PTRACE_SETFPREGS)) || \
    (defined(PT_GETFPREGS) && defined(PT_SETFPREGS))
  int ptrace_getfpregs = PTRACE_GETFPREGS;
  int ptrace_setfpregs = PTRACE_SETFPREGS;
#else
  int ptrace_getfpregs = -1;
  int ptrace_setfpregs = -1;
#endif
#if (defined(PTRACE_GETFPXREGS) && defined(PTRACE_SETFPXREGS)) || \
    (defined(PT_GETFPXREGS) && defined(PT_SETFPXREGS))
  int ptrace_getfpxregs = PTRACE_GETFPXREGS;
  int ptrace_setfpxregs = PTRACE_SETFPXREGS;
#else
  int ptrace_getfpxregs = -1;
  int ptrace_setfpxregs = -1;
#endif // PTRACE_GETFPXREGS/PTRACE_SETFPXREGS
#if defined(PTRACE_GETVFPREGS) && defined(PTRACE_SETVFPREGS)
  int ptrace_getvfpregs = PTRACE_GETVFPREGS;
  int ptrace_setvfpregs = PTRACE_SETVFPREGS;
#else
  int ptrace_getvfpregs = -1;
  int ptrace_setvfpregs = -1;
#endif
  int ptrace_geteventmsg = PTRACE_GETEVENTMSG;
#if (defined(PTRACE_GETSIGINFO) && defined(PTRACE_SETSIGINFO)) ||              \
    (defined(PT_GETSIGINFO) && defined(PT_SETSIGINFO))
  int ptrace_getsiginfo = PTRACE_GETSIGINFO;
  int ptrace_setsiginfo = PTRACE_SETSIGINFO;
#else
  int ptrace_getsiginfo = -1;
  int ptrace_setsiginfo = -1;
#endif // PTRACE_GETSIGINFO/PTRACE_SETSIGINFO
#if defined(PTRACE_GETREGSET) && defined(PTRACE_SETREGSET)
  int ptrace_getregset = PTRACE_GETREGSET;
  int ptrace_setregset = PTRACE_SETREGSET;
#else
  int ptrace_getregset = -1;
  int ptrace_setregset = -1;
#endif // PTRACE_GETREGSET/PTRACE_SETREGSET
#endif

  unsigned path_max = PATH_MAX;

  // ioctl arguments
  unsigned struct_ifreq_sz = sizeof(struct ifreq);
  unsigned struct_termios_sz = sizeof(struct termios);
  unsigned struct_winsize_sz = sizeof(struct winsize);

#if SANITIZER_LINUX
  unsigned struct_arpreq_sz = sizeof(struct arpreq);
  unsigned struct_cdrom_msf_sz = sizeof(struct cdrom_msf);
  unsigned struct_cdrom_multisession_sz = sizeof(struct cdrom_multisession);
  unsigned struct_cdrom_read_audio_sz = sizeof(struct cdrom_read_audio);
  unsigned struct_cdrom_subchnl_sz = sizeof(struct cdrom_subchnl);
  unsigned struct_cdrom_ti_sz = sizeof(struct cdrom_ti);
  unsigned struct_cdrom_tocentry_sz = sizeof(struct cdrom_tocentry);
  unsigned struct_cdrom_tochdr_sz = sizeof(struct cdrom_tochdr);
  unsigned struct_cdrom_volctrl_sz = sizeof(struct cdrom_volctrl);
  unsigned struct_ff_effect_sz = sizeof(struct ff_effect);
  unsigned struct_floppy_drive_params_sz = sizeof(struct floppy_drive_params);
  unsigned struct_floppy_drive_struct_sz = sizeof(struct floppy_drive_struct);
  unsigned struct_floppy_fdc_state_sz = sizeof(struct floppy_fdc_state);
  unsigned struct_floppy_max_errors_sz = sizeof(struct floppy_max_errors);
  unsigned struct_floppy_raw_cmd_sz = sizeof(struct floppy_raw_cmd);
  unsigned struct_floppy_struct_sz = sizeof(struct floppy_struct);
  unsigned struct_floppy_write_errors_sz = sizeof(struct floppy_write_errors);
  unsigned struct_format_descr_sz = sizeof(struct format_descr);
  unsigned struct_hd_driveid_sz = sizeof(struct hd_driveid);
  unsigned struct_hd_geometry_sz = sizeof(struct hd_geometry);
  unsigned struct_input_absinfo_sz = sizeof(struct input_absinfo);
  unsigned struct_input_id_sz = sizeof(struct input_id);
  unsigned struct_mtpos_sz = sizeof(struct mtpos);
  unsigned struct_rtentry_sz = sizeof(struct rtentry);
  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);
  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);
  unsigned struct_vt_stat_sz = sizeof(struct vt_stat);
#endif // SANITIZER_LINUX

#if SANITIZER_LINUX || SANITIZER_FREEBSD
#if SOUND_VERSION >= 0x040000
  unsigned struct_copr_buffer_sz = 0;
  unsigned struct_copr_debug_buf_sz = 0;
  unsigned struct_copr_msg_sz = 0;
#else
  unsigned struct_copr_buffer_sz = sizeof(struct copr_buffer);
  unsigned struct_copr_debug_buf_sz = sizeof(struct copr_debug_buf);
  unsigned struct_copr_msg_sz = sizeof(struct copr_msg);
#endif
  unsigned struct_midi_info_sz = sizeof(struct midi_info);
  unsigned struct_mtget_sz = sizeof(struct mtget);
  unsigned struct_mtop_sz = sizeof(struct mtop);
  unsigned struct_sbi_instrument_sz = sizeof(struct sbi_instrument);
  unsigned struct_seq_event_rec_sz = sizeof(struct seq_event_rec);
  unsigned struct_synth_info_sz = sizeof(struct synth_info);
  unsigned struct_vt_mode_sz = sizeof(struct vt_mode);
#endif // SANITIZER_LINUX || SANITIZER_FREEBSD

#if SANITIZER_LINUX && !SANITIZER_ANDROID
  unsigned struct_ax25_parms_struct_sz = sizeof(struct ax25_parms_struct);
  unsigned struct_cyclades_monitor_sz = sizeof(struct cyclades_monitor);
#if EV_VERSION > (0x010000)
  unsigned struct_input_keymap_entry_sz = sizeof(struct input_keymap_entry);
#else
  unsigned struct_input_keymap_entry_sz = 0;
#endif
  unsigned struct_ipx_config_data_sz = sizeof(struct ipx_config_data);
  unsigned struct_kbdiacrs_sz = sizeof(struct kbdiacrs);
  unsigned struct_kbentry_sz = sizeof(struct kbentry);
  unsigned struct_kbkeycode_sz = sizeof(struct kbkeycode);
  unsigned struct_kbsentry_sz = sizeof(struct kbsentry);
  unsigned struct_mtconfiginfo_sz = sizeof(struct mtconfiginfo);
  unsigned struct_nr_parms_struct_sz = sizeof(struct nr_parms_struct);
  unsigned struct_scc_modem_sz = sizeof(struct scc_modem);
  unsigned struct_scc_stat_sz = sizeof(struct scc_stat);
  unsigned struct_serial_multiport_struct_sz
      = sizeof(struct serial_multiport_struct);
  unsigned struct_serial_struct_sz = sizeof(struct serial_struct);
  unsigned struct_sockaddr_ax25_sz = sizeof(struct sockaddr_ax25);
  unsigned struct_unimapdesc_sz = sizeof(struct unimapdesc);
  unsigned struct_unimapinit_sz = sizeof(struct unimapinit);
#endif // SANITIZER_LINUX && !SANITIZER_ANDROID

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
  unsigned struct_audio_buf_info_sz = sizeof(struct audio_buf_info);
  unsigned struct_ppp_stats_sz = sizeof(struct ppp_stats);
#endif // (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID

#if !SANITIZER_ANDROID && !SANITIZER_MAC
  unsigned struct_sioc_sg_req_sz = sizeof(struct sioc_sg_req);
  unsigned struct_sioc_vif_req_sz = sizeof(struct sioc_vif_req);
#endif

  const unsigned IOCTL_NOT_PRESENT = 0;

  unsigned IOCTL_FIOASYNC = FIOASYNC;
  unsigned IOCTL_FIOCLEX = FIOCLEX;
  unsigned IOCTL_FIOGETOWN = FIOGETOWN;
  unsigned IOCTL_FIONBIO = FIONBIO;
  unsigned IOCTL_FIONCLEX = FIONCLEX;
  unsigned IOCTL_FIOSETOWN = FIOSETOWN;
  unsigned IOCTL_SIOCADDMULTI = SIOCADDMULTI;
  unsigned IOCTL_SIOCATMARK = SIOCATMARK;
  unsigned IOCTL_SIOCDELMULTI = SIOCDELMULTI;
  unsigned IOCTL_SIOCGIFADDR = SIOCGIFADDR;
  unsigned IOCTL_SIOCGIFBRDADDR = SIOCGIFBRDADDR;
  unsigned IOCTL_SIOCGIFCONF = SIOCGIFCONF;
  unsigned IOCTL_SIOCGIFDSTADDR = SIOCGIFDSTADDR;
  unsigned IOCTL_SIOCGIFFLAGS = SIOCGIFFLAGS;
  unsigned IOCTL_SIOCGIFMETRIC = SIOCGIFMETRIC;
  unsigned IOCTL_SIOCGIFMTU = SIOCGIFMTU;
  unsigned IOCTL_SIOCGIFNETMASK = SIOCGIFNETMASK;
  unsigned IOCTL_SIOCGPGRP = SIOCGPGRP;
  unsigned IOCTL_SIOCSIFADDR = SIOCSIFADDR;
  unsigned IOCTL_SIOCSIFBRDADDR = SIOCSIFBRDADDR;
  unsigned IOCTL_SIOCSIFDSTADDR = SIOCSIFDSTADDR;
  unsigned IOCTL_SIOCSIFFLAGS = SIOCSIFFLAGS;
  unsigned IOCTL_SIOCSIFMETRIC = SIOCSIFMETRIC;
  unsigned IOCTL_SIOCSIFMTU = SIOCSIFMTU;
  unsigned IOCTL_SIOCSIFNETMASK = SIOCSIFNETMASK;
  unsigned IOCTL_SIOCSPGRP = SIOCSPGRP;
  unsigned IOCTL_TIOCCONS = TIOCCONS;
  unsigned IOCTL_TIOCEXCL = TIOCEXCL;
  unsigned IOCTL_TIOCGETD = TIOCGETD;
  unsigned IOCTL_TIOCGPGRP = TIOCGPGRP;
  unsigned IOCTL_TIOCGWINSZ = TIOCGWINSZ;
  unsigned IOCTL_TIOCMBIC = TIOCMBIC;
  unsigned IOCTL_TIOCMBIS = TIOCMBIS;
  unsigned IOCTL_TIOCMGET = TIOCMGET;
  unsigned IOCTL_TIOCMSET = TIOCMSET;
  unsigned IOCTL_TIOCNOTTY = TIOCNOTTY;
  unsigned IOCTL_TIOCNXCL = TIOCNXCL;
  unsigned IOCTL_TIOCOUTQ = TIOCOUTQ;
  unsigned IOCTL_TIOCPKT = TIOCPKT;
  unsigned IOCTL_TIOCSCTTY = TIOCSCTTY;
  unsigned IOCTL_TIOCSETD = TIOCSETD;
  unsigned IOCTL_TIOCSPGRP = TIOCSPGRP;
  unsigned IOCTL_TIOCSTI = TIOCSTI;
  unsigned IOCTL_TIOCSWINSZ = TIOCSWINSZ;
#if ((SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID)
  unsigned IOCTL_SIOCGETSGCNT = SIOCGETSGCNT;
  unsigned IOCTL_SIOCGETVIFCNT = SIOCGETVIFCNT;
#endif

#if SANITIZER_LINUX
  unsigned IOCTL_EVIOCGABS = EVIOCGABS(0);
  unsigned IOCTL_EVIOCGBIT = EVIOCGBIT(0, 0);
  unsigned IOCTL_EVIOCGEFFECTS = EVIOCGEFFECTS;
  unsigned IOCTL_EVIOCGID = EVIOCGID;
  unsigned IOCTL_EVIOCGKEY = EVIOCGKEY(0);
  unsigned IOCTL_EVIOCGKEYCODE = EVIOCGKEYCODE;
  unsigned IOCTL_EVIOCGLED = EVIOCGLED(0);
  unsigned IOCTL_EVIOCGNAME = EVIOCGNAME(0);
  unsigned IOCTL_EVIOCGPHYS = EVIOCGPHYS(0);
  unsigned IOCTL_EVIOCGRAB = EVIOCGRAB;
  unsigned IOCTL_EVIOCGREP = EVIOCGREP;
  unsigned IOCTL_EVIOCGSND = EVIOCGSND(0);
  unsigned IOCTL_EVIOCGSW = EVIOCGSW(0);
  unsigned IOCTL_EVIOCGUNIQ = EVIOCGUNIQ(0);
  unsigned IOCTL_EVIOCGVERSION = EVIOCGVERSION;
  unsigned IOCTL_EVIOCRMFF = EVIOCRMFF;
  unsigned IOCTL_EVIOCSABS = EVIOCSABS(0);
  unsigned IOCTL_EVIOCSFF = EVIOCSFF;
  unsigned IOCTL_EVIOCSKEYCODE = EVIOCSKEYCODE;
  unsigned IOCTL_EVIOCSREP = EVIOCSREP;
  unsigned IOCTL_BLKFLSBUF = BLKFLSBUF;
  unsigned IOCTL_BLKGETSIZE = BLKGETSIZE;
  unsigned IOCTL_BLKRAGET = BLKRAGET;
  unsigned IOCTL_BLKRASET = BLKRASET;
  unsigned IOCTL_BLKROGET = BLKROGET;
  unsigned IOCTL_BLKROSET = BLKROSET;
  unsigned IOCTL_BLKRRPART = BLKRRPART;
  unsigned IOCTL_CDROMAUDIOBUFSIZ = CDROMAUDIOBUFSIZ;
  unsigned IOCTL_CDROMEJECT = CDROMEJECT;
  unsigned IOCTL_CDROMEJECT_SW = CDROMEJECT_SW;
  unsigned IOCTL_CDROMMULTISESSION = CDROMMULTISESSION;
  unsigned IOCTL_CDROMPAUSE = CDROMPAUSE;
  unsigned IOCTL_CDROMPLAYMSF = CDROMPLAYMSF;
  unsigned IOCTL_CDROMPLAYTRKIND = CDROMPLAYTRKIND;
  unsigned IOCTL_CDROMREADAUDIO = CDROMREADAUDIO;
  unsigned IOCTL_CDROMREADCOOKED = CDROMREADCOOKED;
  unsigned IOCTL_CDROMREADMODE1 = CDROMREADMODE1;
  unsigned IOCTL_CDROMREADMODE2 = CDROMREADMODE2;
  unsigned IOCTL_CDROMREADRAW = CDROMREADRAW;
  unsigned IOCTL_CDROMREADTOCENTRY = CDROMREADTOCENTRY;
  unsigned IOCTL_CDROMREADTOCHDR = CDROMREADTOCHDR;
  unsigned IOCTL_CDROMRESET = CDROMRESET;
  unsigned IOCTL_CDROMRESUME = CDROMRESUME;
  unsigned IOCTL_CDROMSEEK = CDROMSEEK;
  unsigned IOCTL_CDROMSTART = CDROMSTART;
  unsigned IOCTL_CDROMSTOP = CDROMSTOP;
  unsigned IOCTL_CDROMSUBCHNL = CDROMSUBCHNL;
  unsigned IOCTL_CDROMVOLCTRL = CDROMVOLCTRL;
  unsigned IOCTL_CDROMVOLREAD = CDROMVOLREAD;
  unsigned IOCTL_CDROM_GET_UPC = CDROM_GET_UPC;
  unsigned IOCTL_FDCLRPRM = FDCLRPRM;
  unsigned IOCTL_FDDEFPRM = FDDEFPRM;
  unsigned IOCTL_FDFLUSH = FDFLUSH;
  unsigned IOCTL_FDFMTBEG = FDFMTBEG;
  unsigned IOCTL_FDFMTEND = FDFMTEND;
  unsigned IOCTL_FDFMTTRK = FDFMTTRK;
  unsigned IOCTL_FDGETDRVPRM = FDGETDRVPRM;
  unsigned IOCTL_FDGETDRVSTAT = FDGETDRVSTAT;
  unsigned IOCTL_FDGETDRVTYP = FDGETDRVTYP;
  unsigned IOCTL_FDGETFDCSTAT = FDGETFDCSTAT;
  unsigned IOCTL_FDGETMAXERRS = FDGETMAXERRS;
  unsigned IOCTL_FDGETPRM = FDGETPRM;
  unsigned IOCTL_FDMSGOFF = FDMSGOFF;
  unsigned IOCTL_FDMSGON = FDMSGON;
  unsigned IOCTL_FDPOLLDRVSTAT = FDPOLLDRVSTAT;
  unsigned IOCTL_FDRAWCMD = FDRAWCMD;
  unsigned IOCTL_FDRESET = FDRESET;
  unsigned IOCTL_FDSETDRVPRM = FDSETDRVPRM;
  unsigned IOCTL_FDSETEMSGTRESH = FDSETEMSGTRESH;
  unsigned IOCTL_FDSETMAXERRS = FDSETMAXERRS;
  unsigned IOCTL_FDSETPRM = FDSETPRM;
  unsigned IOCTL_FDTWADDLE = FDTWADDLE;
  unsigned IOCTL_FDWERRORCLR = FDWERRORCLR;
  unsigned IOCTL_FDWERRORGET = FDWERRORGET;
  unsigned IOCTL_HDIO_DRIVE_CMD = HDIO_DRIVE_CMD;
  unsigned IOCTL_HDIO_GETGEO = HDIO_GETGEO;
  unsigned IOCTL_HDIO_GET_32BIT = HDIO_GET_32BIT;
  unsigned IOCTL_HDIO_GET_DMA = HDIO_GET_DMA;
  unsigned IOCTL_HDIO_GET_IDENTITY = HDIO_GET_IDENTITY;
  unsigned IOCTL_HDIO_GET_KEEPSETTINGS = HDIO_GET_KEEPSETTINGS;
  unsigned IOCTL_HDIO_GET_MULTCOUNT = HDIO_GET_MULTCOUNT;
  unsigned IOCTL_HDIO_GET_NOWERR = HDIO_GET_NOWERR;
  unsigned IOCTL_HDIO_GET_UNMASKINTR = HDIO_GET_UNMASKINTR;
  unsigned IOCTL_HDIO_SET_32BIT = HDIO_SET_32BIT;
  unsigned IOCTL_HDIO_SET_DMA = HDIO_SET_DMA;
  unsigned IOCTL_HDIO_SET_KEEPSETTINGS = HDIO_SET_KEEPSETTINGS;
  unsigned IOCTL_HDIO_SET_MULTCOUNT = HDIO_SET_MULTCOUNT;
  unsigned IOCTL_HDIO_SET_NOWERR = HDIO_SET_NOWERR;
  unsigned IOCTL_HDIO_SET_UNMASKINTR = HDIO_SET_UNMASKINTR;
  unsigned IOCTL_MTIOCPOS = MTIOCPOS;
  unsigned IOCTL_PPPIOCGASYNCMAP = PPPIOCGASYNCMAP;
  unsigned IOCTL_PPPIOCGDEBUG = PPPIOCGDEBUG;
  unsigned IOCTL_PPPIOCGFLAGS = PPPIOCGFLAGS;
  unsigned IOCTL_PPPIOCGUNIT = PPPIOCGUNIT;
  unsigned IOCTL_PPPIOCGXASYNCMAP = PPPIOCGXASYNCMAP;
  unsigned IOCTL_PPPIOCSASYNCMAP = PPPIOCSASYNCMAP;
  unsigned IOCTL_PPPIOCSDEBUG = PPPIOCSDEBUG;
  unsigned IOCTL_PPPIOCSFLAGS = PPPIOCSFLAGS;
  unsigned IOCTL_PPPIOCSMAXCID = PPPIOCSMAXCID;
  unsigned IOCTL_PPPIOCSMRU = PPPIOCSMRU;
  unsigned IOCTL_PPPIOCSXASYNCMAP = PPPIOCSXASYNCMAP;
  unsigned IOCTL_SIOCADDRT = SIOCADDRT;
  unsigned IOCTL_SIOCDARP = SIOCDARP;
  unsigned IOCTL_SIOCDELRT = SIOCDELRT;
  unsigned IOCTL_SIOCDRARP = SIOCDRARP;
  unsigned IOCTL_SIOCGARP = SIOCGARP;
  unsigned IOCTL_SIOCGIFENCAP = SIOCGIFENCAP;
  unsigned IOCTL_SIOCGIFHWADDR = SIOCGIFHWADDR;
  unsigned IOCTL_SIOCGIFMAP = SIOCGIFMAP;
  unsigned IOCTL_SIOCGIFMEM = SIOCGIFMEM;
  unsigned IOCTL_SIOCGIFNAME = SIOCGIFNAME;
  unsigned IOCTL_SIOCGIFSLAVE = SIOCGIFSLAVE;
  unsigned IOCTL_SIOCGRARP = SIOCGRARP;
  unsigned IOCTL_SIOCGSTAMP = SIOCGSTAMP;
  unsigned IOCTL_SIOCSARP = SIOCSARP;
  unsigned IOCTL_SIOCSIFENCAP = SIOCSIFENCAP;
  unsigned IOCTL_SIOCSIFHWADDR = SIOCSIFHWADDR;
  unsigned IOCTL_SIOCSIFLINK = SIOCSIFLINK;
  unsigned IOCTL_SIOCSIFMAP = SIOCSIFMAP;
  unsigned IOCTL_SIOCSIFMEM = SIOCSIFMEM;
  unsigned IOCTL_SIOCSIFSLAVE = SIOCSIFSLAVE;
  unsigned IOCTL_SIOCSRARP = SIOCSRARP;
# if SOUND_VERSION >= 0x040000
  unsigned IOCTL_SNDCTL_COPR_HALT = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_LOAD = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_RCODE = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_RCVMSG = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_RDATA = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_RESET = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_RUN = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_SENDMSG = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_WCODE = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_WDATA = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_READ_BITS = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_READ_CHANNELS = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_READ_FILTER = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_READ_RATE = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_WRITE_CHANNELS = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_WRITE_FILTER = IOCTL_NOT_PRESENT;
# else  // SOUND_VERSION
  unsigned IOCTL_SNDCTL_COPR_HALT = SNDCTL_COPR_HALT;
  unsigned IOCTL_SNDCTL_COPR_LOAD = SNDCTL_COPR_LOAD;
  unsigned IOCTL_SNDCTL_COPR_RCODE = SNDCTL_COPR_RCODE;
  unsigned IOCTL_SNDCTL_COPR_RCVMSG = SNDCTL_COPR_RCVMSG;
  unsigned IOCTL_SNDCTL_COPR_RDATA = SNDCTL_COPR_RDATA;
  unsigned IOCTL_SNDCTL_COPR_RESET = SNDCTL_COPR_RESET;
  unsigned IOCTL_SNDCTL_COPR_RUN = SNDCTL_COPR_RUN;
  unsigned IOCTL_SNDCTL_COPR_SENDMSG = SNDCTL_COPR_SENDMSG;
  unsigned IOCTL_SNDCTL_COPR_WCODE = SNDCTL_COPR_WCODE;
  unsigned IOCTL_SNDCTL_COPR_WDATA = SNDCTL_COPR_WDATA;
  unsigned IOCTL_SOUND_PCM_READ_BITS = SOUND_PCM_READ_BITS;
  unsigned IOCTL_SOUND_PCM_READ_CHANNELS = SOUND_PCM_READ_CHANNELS;
  unsigned IOCTL_SOUND_PCM_READ_FILTER = SOUND_PCM_READ_FILTER;
  unsigned IOCTL_SOUND_PCM_READ_RATE = SOUND_PCM_READ_RATE;
  unsigned IOCTL_SOUND_PCM_WRITE_CHANNELS = SOUND_PCM_WRITE_CHANNELS;
  unsigned IOCTL_SOUND_PCM_WRITE_FILTER = SOUND_PCM_WRITE_FILTER;
#endif // SOUND_VERSION
  unsigned IOCTL_TCFLSH = TCFLSH;
  unsigned IOCTL_TCGETA = TCGETA;
  unsigned IOCTL_TCGETS = TCGETS;
  unsigned IOCTL_TCSBRK = TCSBRK;
  unsigned IOCTL_TCSBRKP = TCSBRKP;
  unsigned IOCTL_TCSETA = TCSETA;
  unsigned IOCTL_TCSETAF = TCSETAF;
  unsigned IOCTL_TCSETAW = TCSETAW;
  unsigned IOCTL_TCSETS = TCSETS;
  unsigned IOCTL_TCSETSF = TCSETSF;
  unsigned IOCTL_TCSETSW = TCSETSW;
  unsigned IOCTL_TCXONC = TCXONC;
  unsigned IOCTL_TIOCGLCKTRMIOS = TIOCGLCKTRMIOS;
  unsigned IOCTL_TIOCGSOFTCAR = TIOCGSOFTCAR;
  unsigned IOCTL_TIOCINQ = TIOCINQ;
  unsigned IOCTL_TIOCLINUX = TIOCLINUX;
  unsigned IOCTL_TIOCSERCONFIG = TIOCSERCONFIG;
  unsigned IOCTL_TIOCSERGETLSR = TIOCSERGETLSR;
  unsigned IOCTL_TIOCSERGWILD = TIOCSERGWILD;
  unsigned IOCTL_TIOCSERSWILD = TIOCSERSWILD;
  unsigned IOCTL_TIOCSLCKTRMIOS = TIOCSLCKTRMIOS;
  unsigned IOCTL_TIOCSSOFTCAR = TIOCSSOFTCAR;
  unsigned IOCTL_VT_DISALLOCATE = VT_DISALLOCATE;
  unsigned IOCTL_VT_GETSTATE = VT_GETSTATE;
  unsigned IOCTL_VT_RESIZE = VT_RESIZE;
  unsigned IOCTL_VT_RESIZEX = VT_RESIZEX;
  unsigned IOCTL_VT_SENDSIG = VT_SENDSIG;
#endif // SANITIZER_LINUX

#if SANITIZER_LINUX || SANITIZER_FREEBSD
  unsigned IOCTL_MTIOCGET = MTIOCGET;
  unsigned IOCTL_MTIOCTOP = MTIOCTOP;
  unsigned IOCTL_SNDCTL_DSP_GETBLKSIZE = SNDCTL_DSP_GETBLKSIZE;
  unsigned IOCTL_SNDCTL_DSP_GETFMTS = SNDCTL_DSP_GETFMTS;
  unsigned IOCTL_SNDCTL_DSP_NONBLOCK = SNDCTL_DSP_NONBLOCK;
  unsigned IOCTL_SNDCTL_DSP_POST = SNDCTL_DSP_POST;
  unsigned IOCTL_SNDCTL_DSP_RESET = SNDCTL_DSP_RESET;
  unsigned IOCTL_SNDCTL_DSP_SETFMT = SNDCTL_DSP_SETFMT;
  unsigned IOCTL_SNDCTL_DSP_SETFRAGMENT = SNDCTL_DSP_SETFRAGMENT;
  unsigned IOCTL_SNDCTL_DSP_SPEED = SNDCTL_DSP_SPEED;
  unsigned IOCTL_SNDCTL_DSP_STEREO = SNDCTL_DSP_STEREO;
  unsigned IOCTL_SNDCTL_DSP_SUBDIVIDE = SNDCTL_DSP_SUBDIVIDE;
  unsigned IOCTL_SNDCTL_DSP_SYNC = SNDCTL_DSP_SYNC;
  unsigned IOCTL_SNDCTL_FM_4OP_ENABLE = SNDCTL_FM_4OP_ENABLE;
  unsigned IOCTL_SNDCTL_FM_LOAD_INSTR = SNDCTL_FM_LOAD_INSTR;
  unsigned IOCTL_SNDCTL_MIDI_INFO = SNDCTL_MIDI_INFO;
  unsigned IOCTL_SNDCTL_MIDI_PRETIME = SNDCTL_MIDI_PRETIME;
  unsigned IOCTL_SNDCTL_SEQ_CTRLRATE = SNDCTL_SEQ_CTRLRATE;
  unsigned IOCTL_SNDCTL_SEQ_GETINCOUNT = SNDCTL_SEQ_GETINCOUNT;
  unsigned IOCTL_SNDCTL_SEQ_GETOUTCOUNT = SNDCTL_SEQ_GETOUTCOUNT;
  unsigned IOCTL_SNDCTL_SEQ_NRMIDIS = SNDCTL_SEQ_NRMIDIS;
  unsigned IOCTL_SNDCTL_SEQ_NRSYNTHS = SNDCTL_SEQ_NRSYNTHS;
  unsigned IOCTL_SNDCTL_SEQ_OUTOFBAND = SNDCTL_SEQ_OUTOFBAND;
  unsigned IOCTL_SNDCTL_SEQ_PANIC = SNDCTL_SEQ_PANIC;
  unsigned IOCTL_SNDCTL_SEQ_PERCMODE = SNDCTL_SEQ_PERCMODE;
  unsigned IOCTL_SNDCTL_SEQ_RESET = SNDCTL_SEQ_RESET;
  unsigned IOCTL_SNDCTL_SEQ_RESETSAMPLES = SNDCTL_SEQ_RESETSAMPLES;
  unsigned IOCTL_SNDCTL_SEQ_SYNC = SNDCTL_SEQ_SYNC;
  unsigned IOCTL_SNDCTL_SEQ_TESTMIDI = SNDCTL_SEQ_TESTMIDI;
  unsigned IOCTL_SNDCTL_SEQ_THRESHOLD = SNDCTL_SEQ_THRESHOLD;
  unsigned IOCTL_SNDCTL_SYNTH_INFO = SNDCTL_SYNTH_INFO;
  unsigned IOCTL_SNDCTL_SYNTH_MEMAVL = SNDCTL_SYNTH_MEMAVL;
  unsigned IOCTL_SNDCTL_TMR_CONTINUE = SNDCTL_TMR_CONTINUE;
  unsigned IOCTL_SNDCTL_TMR_METRONOME = SNDCTL_TMR_METRONOME;
  unsigned IOCTL_SNDCTL_TMR_SELECT = SNDCTL_TMR_SELECT;
  unsigned IOCTL_SNDCTL_TMR_SOURCE = SNDCTL_TMR_SOURCE;
  unsigned IOCTL_SNDCTL_TMR_START = SNDCTL_TMR_START;
  unsigned IOCTL_SNDCTL_TMR_STOP = SNDCTL_TMR_STOP;
  unsigned IOCTL_SNDCTL_TMR_TEMPO = SNDCTL_TMR_TEMPO;
  unsigned IOCTL_SNDCTL_TMR_TIMEBASE = SNDCTL_TMR_TIMEBASE;
  unsigned IOCTL_SOUND_MIXER_READ_ALTPCM = SOUND_MIXER_READ_ALTPCM;
  unsigned IOCTL_SOUND_MIXER_READ_BASS = SOUND_MIXER_READ_BASS;
  unsigned IOCTL_SOUND_MIXER_READ_CAPS = SOUND_MIXER_READ_CAPS;
  unsigned IOCTL_SOUND_MIXER_READ_CD = SOUND_MIXER_READ_CD;
  unsigned IOCTL_SOUND_MIXER_READ_DEVMASK = SOUND_MIXER_READ_DEVMASK;
  unsigned IOCTL_SOUND_MIXER_READ_ENHANCE = SOUND_MIXER_READ_ENHANCE;
  unsigned IOCTL_SOUND_MIXER_READ_IGAIN = SOUND_MIXER_READ_IGAIN;
  unsigned IOCTL_SOUND_MIXER_READ_IMIX = SOUND_MIXER_READ_IMIX;
  unsigned IOCTL_SOUND_MIXER_READ_LINE = SOUND_MIXER_READ_LINE;
  unsigned IOCTL_SOUND_MIXER_READ_LINE1 = SOUND_MIXER_READ_LINE1;
  unsigned IOCTL_SOUND_MIXER_READ_LINE2 = SOUND_MIXER_READ_LINE2;
  unsigned IOCTL_SOUND_MIXER_READ_LINE3 = SOUND_MIXER_READ_LINE3;
  unsigned IOCTL_SOUND_MIXER_READ_LOUD = SOUND_MIXER_READ_LOUD;
  unsigned IOCTL_SOUND_MIXER_READ_MIC = SOUND_MIXER_READ_MIC;
  unsigned IOCTL_SOUND_MIXER_READ_MUTE = SOUND_MIXER_READ_MUTE;
  unsigned IOCTL_SOUND_MIXER_READ_OGAIN = SOUND_MIXER_READ_OGAIN;
  unsigned IOCTL_SOUND_MIXER_READ_PCM = SOUND_MIXER_READ_PCM;
  unsigned IOCTL_SOUND_MIXER_READ_RECLEV = SOUND_MIXER_READ_RECLEV;
  unsigned IOCTL_SOUND_MIXER_READ_RECMASK = SOUND_MIXER_READ_RECMASK;
  unsigned IOCTL_SOUND_MIXER_READ_RECSRC = SOUND_MIXER_READ_RECSRC;
  unsigned IOCTL_SOUND_MIXER_READ_SPEAKER = SOUND_MIXER_READ_SPEAKER;
  unsigned IOCTL_SOUND_MIXER_READ_STEREODEVS = SOUND_MIXER_READ_STEREODEVS;
  unsigned IOCTL_SOUND_MIXER_READ_SYNTH = SOUND_MIXER_READ_SYNTH;
  unsigned IOCTL_SOUND_MIXER_READ_TREBLE = SOUND_MIXER_READ_TREBLE;
  unsigned IOCTL_SOUND_MIXER_READ_VOLUME = SOUND_MIXER_READ_VOLUME;
  unsigned IOCTL_SOUND_MIXER_WRITE_ALTPCM = SOUND_MIXER_WRITE_ALTPCM;
  unsigned IOCTL_SOUND_MIXER_WRITE_BASS = SOUND_MIXER_WRITE_BASS;
  unsigned IOCTL_SOUND_MIXER_WRITE_CD = SOUND_MIXER_WRITE_CD;
  unsigned IOCTL_SOUND_MIXER_WRITE_ENHANCE = SOUND_MIXER_WRITE_ENHANCE;
  unsigned IOCTL_SOUND_MIXER_WRITE_IGAIN = SOUND_MIXER_WRITE_IGAIN;
  unsigned IOCTL_SOUND_MIXER_WRITE_IMIX = SOUND_MIXER_WRITE_IMIX;
  unsigned IOCTL_SOUND_MIXER_WRITE_LINE = SOUND_MIXER_WRITE_LINE;
  unsigned IOCTL_SOUND_MIXER_WRITE_LINE1 = SOUND_MIXER_WRITE_LINE1;
  unsigned IOCTL_SOUND_MIXER_WRITE_LINE2 = SOUND_MIXER_WRITE_LINE2;
  unsigned IOCTL_SOUND_MIXER_WRITE_LINE3 = SOUND_MIXER_WRITE_LINE3;
  unsigned IOCTL_SOUND_MIXER_WRITE_LOUD = SOUND_MIXER_WRITE_LOUD;
  unsigned IOCTL_SOUND_MIXER_WRITE_MIC = SOUND_MIXER_WRITE_MIC;
  unsigned IOCTL_SOUND_MIXER_WRITE_MUTE = SOUND_MIXER_WRITE_MUTE;
  unsigned IOCTL_SOUND_MIXER_WRITE_OGAIN = SOUND_MIXER_WRITE_OGAIN;
  unsigned IOCTL_SOUND_MIXER_WRITE_PCM = SOUND_MIXER_WRITE_PCM;
  unsigned IOCTL_SOUND_MIXER_WRITE_RECLEV = SOUND_MIXER_WRITE_RECLEV;
  unsigned IOCTL_SOUND_MIXER_WRITE_RECSRC = SOUND_MIXER_WRITE_RECSRC;
  unsigned IOCTL_SOUND_MIXER_WRITE_SPEAKER = SOUND_MIXER_WRITE_SPEAKER;
  unsigned IOCTL_SOUND_MIXER_WRITE_SYNTH = SOUND_MIXER_WRITE_SYNTH;
  unsigned IOCTL_SOUND_MIXER_WRITE_TREBLE = SOUND_MIXER_WRITE_TREBLE;
  unsigned IOCTL_SOUND_MIXER_WRITE_VOLUME = SOUND_MIXER_WRITE_VOLUME;
  unsigned IOCTL_VT_ACTIVATE = VT_ACTIVATE;
  unsigned IOCTL_VT_GETMODE = VT_GETMODE;
  unsigned IOCTL_VT_OPENQRY = VT_OPENQRY;
  unsigned IOCTL_VT_RELDISP = VT_RELDISP;
  unsigned IOCTL_VT_SETMODE = VT_SETMODE;
  unsigned IOCTL_VT_WAITACTIVE = VT_WAITACTIVE;
#endif // SANITIZER_LINUX || SANITIZER_FREEBSD

#if SANITIZER_LINUX && !SANITIZER_ANDROID
  unsigned IOCTL_CYGETDEFTHRESH = CYGETDEFTHRESH;
  unsigned IOCTL_CYGETDEFTIMEOUT = CYGETDEFTIMEOUT;
  unsigned IOCTL_CYGETMON = CYGETMON;
  unsigned IOCTL_CYGETTHRESH = CYGETTHRESH;
  unsigned IOCTL_CYGETTIMEOUT = CYGETTIMEOUT;
  unsigned IOCTL_CYSETDEFTHRESH = CYSETDEFTHRESH;
  unsigned IOCTL_CYSETDEFTIMEOUT = CYSETDEFTIMEOUT;
  unsigned IOCTL_CYSETTHRESH = CYSETTHRESH;
  unsigned IOCTL_CYSETTIMEOUT = CYSETTIMEOUT;
  unsigned IOCTL_EQL_EMANCIPATE = EQL_EMANCIPATE;
  unsigned IOCTL_EQL_ENSLAVE = EQL_ENSLAVE;
  unsigned IOCTL_EQL_GETMASTRCFG = EQL_GETMASTRCFG;
  unsigned IOCTL_EQL_GETSLAVECFG = EQL_GETSLAVECFG;
  unsigned IOCTL_EQL_SETMASTRCFG = EQL_SETMASTRCFG;
  unsigned IOCTL_EQL_SETSLAVECFG = EQL_SETSLAVECFG;
#if EV_VERSION > (0x010000)
  unsigned IOCTL_EVIOCGKEYCODE_V2 = EVIOCGKEYCODE_V2;
  unsigned IOCTL_EVIOCGPROP = EVIOCGPROP(0);
  unsigned IOCTL_EVIOCSKEYCODE_V2 = EVIOCSKEYCODE_V2;
#else
  unsigned IOCTL_EVIOCGKEYCODE_V2 = IOCTL_NOT_PRESENT;
  unsigned IOCTL_EVIOCGPROP = IOCTL_NOT_PRESENT;
  unsigned IOCTL_EVIOCSKEYCODE_V2 = IOCTL_NOT_PRESENT;
#endif
  unsigned IOCTL_FS_IOC_GETFLAGS = FS_IOC_GETFLAGS;
  unsigned IOCTL_FS_IOC_GETVERSION = FS_IOC_GETVERSION;
  unsigned IOCTL_FS_IOC_SETFLAGS = FS_IOC_SETFLAGS;
  unsigned IOCTL_FS_IOC_SETVERSION = FS_IOC_SETVERSION;
  unsigned IOCTL_GIO_CMAP = GIO_CMAP;
  unsigned IOCTL_GIO_FONT = GIO_FONT;
  unsigned IOCTL_GIO_UNIMAP = GIO_UNIMAP;
  unsigned IOCTL_GIO_UNISCRNMAP = GIO_UNISCRNMAP;
  unsigned IOCTL_KDADDIO = KDADDIO;
  unsigned IOCTL_KDDELIO = KDDELIO;
  unsigned IOCTL_KDGETKEYCODE = KDGETKEYCODE;
  unsigned IOCTL_KDGKBDIACR = KDGKBDIACR;
  unsigned IOCTL_KDGKBENT = KDGKBENT;
  unsigned IOCTL_KDGKBLED = KDGKBLED;
  unsigned IOCTL_KDGKBMETA = KDGKBMETA;
  unsigned IOCTL_KDGKBSENT = KDGKBSENT;
  unsigned IOCTL_KDMAPDISP = KDMAPDISP;
  unsigned IOCTL_KDSETKEYCODE = KDSETKEYCODE;
  unsigned IOCTL_KDSIGACCEPT = KDSIGACCEPT;
  unsigned IOCTL_KDSKBDIACR = KDSKBDIACR;
  unsigned IOCTL_KDSKBENT = KDSKBENT;
  unsigned IOCTL_KDSKBLED = KDSKBLED;
  unsigned IOCTL_KDSKBMETA = KDSKBMETA;
  unsigned IOCTL_KDSKBSENT = KDSKBSENT;
  unsigned IOCTL_KDUNMAPDISP = KDUNMAPDISP;
  unsigned IOCTL_LPABORT = LPABORT;
  unsigned IOCTL_LPABORTOPEN = LPABORTOPEN;
  unsigned IOCTL_LPCAREFUL = LPCAREFUL;
  unsigned IOCTL_LPCHAR = LPCHAR;
  unsigned IOCTL_LPGETIRQ = LPGETIRQ;
  unsigned IOCTL_LPGETSTATUS = LPGETSTATUS;
  unsigned IOCTL_LPRESET = LPRESET;
  unsigned IOCTL_LPSETIRQ = LPSETIRQ;
  unsigned IOCTL_LPTIME = LPTIME;
  unsigned IOCTL_LPWAIT = LPWAIT;
  unsigned IOCTL_MTIOCGETCONFIG = MTIOCGETCONFIG;
  unsigned IOCTL_MTIOCSETCONFIG = MTIOCSETCONFIG;
  unsigned IOCTL_PIO_CMAP = PIO_CMAP;
  unsigned IOCTL_PIO_FONT = PIO_FONT;
  unsigned IOCTL_PIO_UNIMAP = PIO_UNIMAP;
  unsigned IOCTL_PIO_UNIMAPCLR = PIO_UNIMAPCLR;
  unsigned IOCTL_PIO_UNISCRNMAP = PIO_UNISCRNMAP;
  unsigned IOCTL_SCSI_IOCTL_GET_IDLUN = SCSI_IOCTL_GET_IDLUN;
  unsigned IOCTL_SCSI_IOCTL_PROBE_HOST = SCSI_IOCTL_PROBE_HOST;
  unsigned IOCTL_SCSI_IOCTL_TAGGED_DISABLE = SCSI_IOCTL_TAGGED_DISABLE;
  unsigned IOCTL_SCSI_IOCTL_TAGGED_ENABLE = SCSI_IOCTL_TAGGED_ENABLE;
  unsigned IOCTL_SIOCAIPXITFCRT = SIOCAIPXITFCRT;
  unsigned IOCTL_SIOCAIPXPRISLT = SIOCAIPXPRISLT;
  unsigned IOCTL_SIOCAX25ADDUID = SIOCAX25ADDUID;
  unsigned IOCTL_SIOCAX25DELUID = SIOCAX25DELUID;
  unsigned IOCTL_SIOCAX25GETPARMS = SIOCAX25GETPARMS;
  unsigned IOCTL_SIOCAX25GETUID = SIOCAX25GETUID;
  unsigned IOCTL_SIOCAX25NOUID = SIOCAX25NOUID;
  unsigned IOCTL_SIOCAX25SETPARMS = SIOCAX25SETPARMS;
  unsigned IOCTL_SIOCDEVPLIP = SIOCDEVPLIP;
  unsigned IOCTL_SIOCIPXCFGDATA = SIOCIPXCFGDATA;
  unsigned IOCTL_SIOCNRDECOBS = SIOCNRDECOBS;
  unsigned IOCTL_SIOCNRGETPARMS = SIOCNRGETPARMS;
  unsigned IOCTL_SIOCNRRTCTL = SIOCNRRTCTL;
  unsigned IOCTL_SIOCNRSETPARMS = SIOCNRSETPARMS;
  unsigned IOCTL_TIOCGSERIAL = TIOCGSERIAL;
  unsigned IOCTL_TIOCSERGETMULTI = TIOCSERGETMULTI;
  unsigned IOCTL_TIOCSERSETMULTI = TIOCSERSETMULTI;
  unsigned IOCTL_TIOCSSERIAL = TIOCSSERIAL;
#endif // SANITIZER_LINUX && !SANITIZER_ANDROID

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
  unsigned IOCTL_GIO_SCRNMAP = GIO_SCRNMAP;
  unsigned IOCTL_KDDISABIO = KDDISABIO;
  unsigned IOCTL_KDENABIO = KDENABIO;
  unsigned IOCTL_KDGETLED = KDGETLED;
  unsigned IOCTL_KDGETMODE = KDGETMODE;
  unsigned IOCTL_KDGKBMODE = KDGKBMODE;
  unsigned IOCTL_KDGKBTYPE = KDGKBTYPE;
  unsigned IOCTL_KDMKTONE = KDMKTONE;
  unsigned IOCTL_KDSETLED = KDSETLED;
  unsigned IOCTL_KDSETMODE = KDSETMODE;
  unsigned IOCTL_KDSKBMODE = KDSKBMODE;
  unsigned IOCTL_KIOCSOUND = KIOCSOUND;
  unsigned IOCTL_PIO_SCRNMAP = PIO_SCRNMAP;
  unsigned IOCTL_SNDCTL_DSP_GETISPACE = SNDCTL_DSP_GETISPACE;
  unsigned IOCTL_SNDCTL_DSP_GETOSPACE = SNDCTL_DSP_GETOSPACE;
#endif // (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID

  const int errno_EINVAL = EINVAL;
// EOWNERDEAD is not present in some older platforms.
#if defined(EOWNERDEAD)
  const int errno_EOWNERDEAD = EOWNERDEAD;
#else
  const int errno_EOWNERDEAD = -1;
#endif

  const int si_SEGV_MAPERR = SEGV_MAPERR;
  const int si_SEGV_ACCERR = SEGV_ACCERR;
} // namespace __sanitizer

COMPILER_CHECK(sizeof(__sanitizer_pthread_attr_t) >= sizeof(pthread_attr_t));

COMPILER_CHECK(sizeof(socklen_t) == sizeof(unsigned));
CHECK_TYPE_SIZE(pthread_key_t);

#if SANITIZER_LINUX
// FIXME: We define those on Linux and Mac, but only check on Linux.
COMPILER_CHECK(IOC_NRBITS == _IOC_NRBITS);
COMPILER_CHECK(IOC_TYPEBITS == _IOC_TYPEBITS);
COMPILER_CHECK(IOC_SIZEBITS == _IOC_SIZEBITS);
COMPILER_CHECK(IOC_DIRBITS == _IOC_DIRBITS);
COMPILER_CHECK(IOC_NRMASK == _IOC_NRMASK);
COMPILER_CHECK(IOC_TYPEMASK == _IOC_TYPEMASK);
COMPILER_CHECK(IOC_SIZEMASK == _IOC_SIZEMASK);
COMPILER_CHECK(IOC_DIRMASK == _IOC_DIRMASK);
COMPILER_CHECK(IOC_NRSHIFT == _IOC_NRSHIFT);
COMPILER_CHECK(IOC_TYPESHIFT == _IOC_TYPESHIFT);
COMPILER_CHECK(IOC_SIZESHIFT == _IOC_SIZESHIFT);
COMPILER_CHECK(IOC_DIRSHIFT == _IOC_DIRSHIFT);
COMPILER_CHECK(IOC_NONE == _IOC_NONE);
COMPILER_CHECK(IOC_WRITE == _IOC_WRITE);
COMPILER_CHECK(IOC_READ == _IOC_READ);
COMPILER_CHECK(EVIOC_ABS_MAX == ABS_MAX);
COMPILER_CHECK(EVIOC_EV_MAX == EV_MAX);
COMPILER_CHECK(IOC_SIZE(0x12345678) == _IOC_SIZE(0x12345678));
COMPILER_CHECK(IOC_DIR(0x12345678) == _IOC_DIR(0x12345678));
COMPILER_CHECK(IOC_NR(0x12345678) == _IOC_NR(0x12345678));
COMPILER_CHECK(IOC_TYPE(0x12345678) == _IOC_TYPE(0x12345678));
#endif // SANITIZER_LINUX

#if SANITIZER_LINUX || SANITIZER_FREEBSD
// There are more undocumented fields in dl_phdr_info that we are not interested
// in.
COMPILER_CHECK(sizeof(__sanitizer_dl_phdr_info) <= sizeof(dl_phdr_info));
CHECK_SIZE_AND_OFFSET(dl_phdr_info, dlpi_addr);
CHECK_SIZE_AND_OFFSET(dl_phdr_info, dlpi_name);
CHECK_SIZE_AND_OFFSET(dl_phdr_info, dlpi_phdr);
CHECK_SIZE_AND_OFFSET(dl_phdr_info, dlpi_phnum);
#endif // SANITIZER_LINUX || SANITIZER_FREEBSD

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
CHECK_TYPE_SIZE(glob_t);
CHECK_SIZE_AND_OFFSET(glob_t, gl_pathc);
CHECK_SIZE_AND_OFFSET(glob_t, gl_pathv);
CHECK_SIZE_AND_OFFSET(glob_t, gl_offs);
CHECK_SIZE_AND_OFFSET(glob_t, gl_flags);
CHECK_SIZE_AND_OFFSET(glob_t, gl_closedir);
CHECK_SIZE_AND_OFFSET(glob_t, gl_readdir);
CHECK_SIZE_AND_OFFSET(glob_t, gl_opendir);
CHECK_SIZE_AND_OFFSET(glob_t, gl_lstat);
CHECK_SIZE_AND_OFFSET(glob_t, gl_stat);
#endif

CHECK_TYPE_SIZE(addrinfo);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_flags);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_family);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_socktype);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_protocol);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_protocol);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_addrlen);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_canonname);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_addr);

CHECK_TYPE_SIZE(hostent);
CHECK_SIZE_AND_OFFSET(hostent, h_name);
CHECK_SIZE_AND_OFFSET(hostent, h_aliases);
CHECK_SIZE_AND_OFFSET(hostent, h_addrtype);
CHECK_SIZE_AND_OFFSET(hostent, h_length);
CHECK_SIZE_AND_OFFSET(hostent, h_addr_list);

CHECK_TYPE_SIZE(iovec);
CHECK_SIZE_AND_OFFSET(iovec, iov_base);
CHECK_SIZE_AND_OFFSET(iovec, iov_len);

CHECK_TYPE_SIZE(msghdr);
CHECK_SIZE_AND_OFFSET(msghdr, msg_name);
CHECK_SIZE_AND_OFFSET(msghdr, msg_namelen);
CHECK_SIZE_AND_OFFSET(msghdr, msg_iov);
CHECK_SIZE_AND_OFFSET(msghdr, msg_iovlen);
CHECK_SIZE_AND_OFFSET(msghdr, msg_control);
CHECK_SIZE_AND_OFFSET(msghdr, msg_controllen);
CHECK_SIZE_AND_OFFSET(msghdr, msg_flags);

CHECK_TYPE_SIZE(cmsghdr);
CHECK_SIZE_AND_OFFSET(cmsghdr, cmsg_len);
CHECK_SIZE_AND_OFFSET(cmsghdr, cmsg_level);
CHECK_SIZE_AND_OFFSET(cmsghdr, cmsg_type);

COMPILER_CHECK(sizeof(__sanitizer_dirent) <= sizeof(dirent));
CHECK_SIZE_AND_OFFSET(dirent, d_ino);
#if SANITIZER_MAC
CHECK_SIZE_AND_OFFSET(dirent, d_seekoff);
#elif SANITIZER_FREEBSD
// There is no 'd_off' field on FreeBSD.
#else
CHECK_SIZE_AND_OFFSET(dirent, d_off);
#endif
CHECK_SIZE_AND_OFFSET(dirent, d_reclen);

#if SANITIZER_LINUX && !SANITIZER_ANDROID
COMPILER_CHECK(sizeof(__sanitizer_dirent64) <= sizeof(dirent64));
CHECK_SIZE_AND_OFFSET(dirent64, d_ino);
CHECK_SIZE_AND_OFFSET(dirent64, d_off);
CHECK_SIZE_AND_OFFSET(dirent64, d_reclen);
#endif

CHECK_TYPE_SIZE(ifconf);
CHECK_SIZE_AND_OFFSET(ifconf, ifc_len);
CHECK_SIZE_AND_OFFSET(ifconf, ifc_ifcu);

CHECK_TYPE_SIZE(pollfd);
CHECK_SIZE_AND_OFFSET(pollfd, fd);
CHECK_SIZE_AND_OFFSET(pollfd, events);
CHECK_SIZE_AND_OFFSET(pollfd, revents);

CHECK_TYPE_SIZE(nfds_t);

CHECK_TYPE_SIZE(sigset_t);

COMPILER_CHECK(sizeof(__sanitizer_sigaction) == sizeof(struct sigaction));
// Can't write checks for sa_handler and sa_sigaction due to them being
// preprocessor macros.
CHECK_STRUCT_SIZE_AND_OFFSET(sigaction, sa_mask);
CHECK_STRUCT_SIZE_AND_OFFSET(sigaction, sa_flags);
#if SANITIZER_LINUX
CHECK_STRUCT_SIZE_AND_OFFSET(sigaction, sa_restorer);
#endif

#if SANITIZER_LINUX
CHECK_TYPE_SIZE(__sysctl_args);
CHECK_SIZE_AND_OFFSET(__sysctl_args, name);
CHECK_SIZE_AND_OFFSET(__sysctl_args, nlen);
CHECK_SIZE_AND_OFFSET(__sysctl_args, oldval);
CHECK_SIZE_AND_OFFSET(__sysctl_args, oldlenp);
CHECK_SIZE_AND_OFFSET(__sysctl_args, newval);
CHECK_SIZE_AND_OFFSET(__sysctl_args, newlen);

CHECK_TYPE_SIZE(__kernel_uid_t);
CHECK_TYPE_SIZE(__kernel_gid_t);

#if SANITIZER_USES_UID16_SYSCALLS
CHECK_TYPE_SIZE(__kernel_old_uid_t);
CHECK_TYPE_SIZE(__kernel_old_gid_t);
#endif

CHECK_TYPE_SIZE(__kernel_off_t);
CHECK_TYPE_SIZE(__kernel_loff_t);
CHECK_TYPE_SIZE(__kernel_fd_set);
#endif

#if !SANITIZER_ANDROID
CHECK_TYPE_SIZE(wordexp_t);
CHECK_SIZE_AND_OFFSET(wordexp_t, we_wordc);
CHECK_SIZE_AND_OFFSET(wordexp_t, we_wordv);
CHECK_SIZE_AND_OFFSET(wordexp_t, we_offs);
#endif

CHECK_TYPE_SIZE(tm);
CHECK_SIZE_AND_OFFSET(tm, tm_sec);
CHECK_SIZE_AND_OFFSET(tm, tm_min);
CHECK_SIZE_AND_OFFSET(tm, tm_hour);
CHECK_SIZE_AND_OFFSET(tm, tm_mday);
CHECK_SIZE_AND_OFFSET(tm, tm_mon);
CHECK_SIZE_AND_OFFSET(tm, tm_year);
CHECK_SIZE_AND_OFFSET(tm, tm_wday);
CHECK_SIZE_AND_OFFSET(tm, tm_yday);
CHECK_SIZE_AND_OFFSET(tm, tm_isdst);
CHECK_SIZE_AND_OFFSET(tm, tm_gmtoff);
CHECK_SIZE_AND_OFFSET(tm, tm_zone);

#if SANITIZER_LINUX
CHECK_TYPE_SIZE(mntent);
CHECK_SIZE_AND_OFFSET(mntent, mnt_fsname);
CHECK_SIZE_AND_OFFSET(mntent, mnt_dir);
CHECK_SIZE_AND_OFFSET(mntent, mnt_type);
CHECK_SIZE_AND_OFFSET(mntent, mnt_opts);
CHECK_SIZE_AND_OFFSET(mntent, mnt_freq);
CHECK_SIZE_AND_OFFSET(mntent, mnt_passno);
#endif

CHECK_TYPE_SIZE(ether_addr);

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
CHECK_TYPE_SIZE(ipc_perm);
# if SANITIZER_FREEBSD
CHECK_SIZE_AND_OFFSET(ipc_perm, key);
CHECK_SIZE_AND_OFFSET(ipc_perm, seq);
# else
CHECK_SIZE_AND_OFFSET(ipc_perm, __key);
CHECK_SIZE_AND_OFFSET(ipc_perm, __seq);
# endif
CHECK_SIZE_AND_OFFSET(ipc_perm, uid);
CHECK_SIZE_AND_OFFSET(ipc_perm, gid);
CHECK_SIZE_AND_OFFSET(ipc_perm, cuid);
CHECK_SIZE_AND_OFFSET(ipc_perm, cgid);
#ifndef __GLIBC_PREREQ
#define __GLIBC_PREREQ(x, y) 0
#endif
//#if !defined(__aarch64__) || !SANITIZER_LINUX || __GLIBC_PREREQ (2, 21)
///* On aarch64 glibc 2.20 and earlier provided incorrect mode field.  */
#if !SANITIZER_LINUX || __GLIBC_PREREQ (2, 31)
CHECK_SIZE_AND_OFFSET(ipc_perm, mode);
#endif

CHECK_TYPE_SIZE(shmid_ds);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_perm);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_segsz);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_atime);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_dtime);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_ctime);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_cpid);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_lpid);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_nattch);
#endif

CHECK_TYPE_SIZE(clock_t);

#if SANITIZER_LINUX
CHECK_TYPE_SIZE(clockid_t);
#endif

#if !SANITIZER_ANDROID
CHECK_TYPE_SIZE(ifaddrs);
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_next);
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_name);
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_addr);
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_netmask);
#if SANITIZER_LINUX || SANITIZER_FREEBSD
// Compare against the union, because we can't reach into the union in a
// compliant way.
#ifdef ifa_dstaddr
#undef ifa_dstaddr
#endif
# if SANITIZER_FREEBSD
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_dstaddr);
# else
COMPILER_CHECK(sizeof(((__sanitizer_ifaddrs *)nullptr)->ifa_dstaddr) ==
               sizeof(((ifaddrs *)nullptr)->ifa_ifu));
COMPILER_CHECK(offsetof(__sanitizer_ifaddrs, ifa_dstaddr) ==
               offsetof(ifaddrs, ifa_ifu));
# endif // SANITIZER_FREEBSD
#else
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_dstaddr);
#endif // SANITIZER_LINUX
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_data);
#endif

#if SANITIZER_LINUX
COMPILER_CHECK(sizeof(__sanitizer_mallinfo) == sizeof(struct mallinfo));
#endif

#if !SANITIZER_ANDROID
CHECK_TYPE_SIZE(timeb);
CHECK_SIZE_AND_OFFSET(timeb, time);
CHECK_SIZE_AND_OFFSET(timeb, millitm);
CHECK_SIZE_AND_OFFSET(timeb, timezone);
CHECK_SIZE_AND_OFFSET(timeb, dstflag);
#endif

CHECK_TYPE_SIZE(passwd);
CHECK_SIZE_AND_OFFSET(passwd, pw_name);
CHECK_SIZE_AND_OFFSET(passwd, pw_passwd);
CHECK_SIZE_AND_OFFSET(passwd, pw_uid);
CHECK_SIZE_AND_OFFSET(passwd, pw_gid);
CHECK_SIZE_AND_OFFSET(passwd, pw_dir);
CHECK_SIZE_AND_OFFSET(passwd, pw_shell);

#if !SANITIZER_ANDROID
CHECK_SIZE_AND_OFFSET(passwd, pw_gecos);
#endif

#if SANITIZER_MAC
CHECK_SIZE_AND_OFFSET(passwd, pw_change);
CHECK_SIZE_AND_OFFSET(passwd, pw_expire);
CHECK_SIZE_AND_OFFSET(passwd, pw_class);
#endif


CHECK_TYPE_SIZE(group);
CHECK_SIZE_AND_OFFSET(group, gr_name);
CHECK_SIZE_AND_OFFSET(group, gr_passwd);
CHECK_SIZE_AND_OFFSET(group, gr_gid);
CHECK_SIZE_AND_OFFSET(group, gr_mem);

#if HAVE_RPC_XDR_H || HAVE_TIRPC_RPC_XDR_H
CHECK_TYPE_SIZE(XDR);
CHECK_SIZE_AND_OFFSET(XDR, x_op);
CHECK_SIZE_AND_OFFSET(XDR, x_ops);
CHECK_SIZE_AND_OFFSET(XDR, x_public);
CHECK_SIZE_AND_OFFSET(XDR, x_private);
CHECK_SIZE_AND_OFFSET(XDR, x_base);
CHECK_SIZE_AND_OFFSET(XDR, x_handy);
COMPILER_CHECK(__sanitizer_XDR_ENCODE == XDR_ENCODE);
COMPILER_CHECK(__sanitizer_XDR_DECODE == XDR_DECODE);
COMPILER_CHECK(__sanitizer_XDR_FREE == XDR_FREE);
#endif

#if SANITIZER_LINUX && !SANITIZER_ANDROID
COMPILER_CHECK(sizeof(__sanitizer_FILE) <= sizeof(FILE));
CHECK_SIZE_AND_OFFSET(FILE, _flags);
CHECK_SIZE_AND_OFFSET(FILE, _IO_read_ptr);
CHECK_SIZE_AND_OFFSET(FILE, _IO_read_end);
CHECK_SIZE_AND_OFFSET(FILE, _IO_read_base);
CHECK_SIZE_AND_OFFSET(FILE, _IO_write_ptr);
CHECK_SIZE_AND_OFFSET(FILE, _IO_write_end);
CHECK_SIZE_AND_OFFSET(FILE, _IO_write_base);
CHECK_SIZE_AND_OFFSET(FILE, _IO_buf_base);
CHECK_SIZE_AND_OFFSET(FILE, _IO_buf_end);
CHECK_SIZE_AND_OFFSET(FILE, _IO_save_base);
CHECK_SIZE_AND_OFFSET(FILE, _IO_backup_base);
CHECK_SIZE_AND_OFFSET(FILE, _IO_save_end);
CHECK_SIZE_AND_OFFSET(FILE, _markers);
CHECK_SIZE_AND_OFFSET(FILE, _chain);
CHECK_SIZE_AND_OFFSET(FILE, _fileno);
#endif

#if SANITIZER_LINUX && !SANITIZER_ANDROID
COMPILER_CHECK(sizeof(__sanitizer__obstack_chunk) <= sizeof(_obstack_chunk));
CHECK_SIZE_AND_OFFSET(_obstack_chunk, limit);
CHECK_SIZE_AND_OFFSET(_obstack_chunk, prev);
CHECK_TYPE_SIZE(obstack);
CHECK_SIZE_AND_OFFSET(obstack, chunk_size);
CHECK_SIZE_AND_OFFSET(obstack, chunk);
CHECK_SIZE_AND_OFFSET(obstack, object_base);
CHECK_SIZE_AND_OFFSET(obstack, next_free);

CHECK_TYPE_SIZE(cookie_io_functions_t);
CHECK_SIZE_AND_OFFSET(cookie_io_functions_t, read);
CHECK_SIZE_AND_OFFSET(cookie_io_functions_t, write);
CHECK_SIZE_AND_OFFSET(cookie_io_functions_t, seek);
CHECK_SIZE_AND_OFFSET(cookie_io_functions_t, close);
#endif

#if SANITIZER_LINUX || SANITIZER_FREEBSD
CHECK_TYPE_SIZE(sem_t);
#endif

#endif // SANITIZER_LINUX || SANITIZER_FREEBSD || SANITIZER_MAC

````

## Full Trace Log

````log

Found 1 patch operation(s) to perform.
Fuzzy matching enabled with threshold: 0.70
debug: apply_patches_to_dir: applying 1 patch(es) to 'src/gcc/' (dry_run=false, fuzz=0.70)
debug:   [1/1] Applying patch for 'libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc' (2 hunk(s))
Applying patch to: libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc
debug:   apply_patch_to_file: target_dir='src/gcc/', hunks=2, dry_run=false, fuzz=0.70
trace:   Checking path safety for base 'src/gcc/' and relative path 'libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc'
trace:   ensure_path_is_safe: canonicalized base directory '<TARGET_DIR>'
trace:   ensure_path_is_safe: processing component 'Normal("libsanitizer")' on virtual path '<TARGET_DIR>'
trace:   ensure_path_is_safe: processing component 'Normal("sanitizer_common")' on virtual path '<TARGET_DIR>/libsanitizer'
trace:   ensure_path_is_safe: processing component 'Normal("sanitizer_platform_limits_posix.cc")' on virtual path '<TARGET_DIR>/libsanitizer/sanitizer_common'
trace:   Path safety verified: 'libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc' safely resolves to '<TARGET_DIR>/libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc'
debug:   Resolved safe target path: '<TARGET_DIR>/libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc'
debug:   Target file exists: '<TARGET_DIR>/libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc'. Reading content...
trace:     Read 49626 bytes (1271 lines) from target file.
debug:   Applying patch logic to content in-memory...
debug: apply_patch_to_content: patch for 'libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc' (2 hunks), original content: 49626 bytes
debug:   apply_patch_to_lines called with 1271 lines of original content.
debug: resolve_hunk_line_hints: evaluating 2 hunk(s) across 1271 target lines
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:   Hunk 1: already has explicit line hint 153
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:   Hunk 2: already has explicit line hint 400
trace: resolve_hunk_line_hints: beginning relaxation pass 1
debug: resolve_hunk_line_hints: completed hint resolution. 2/2 hunk(s) have anchors.
debug: HunkApplier: initialized with 2 hunk(s) across 1271 line(s) of target content (fuzz_factor=0.70, dry_run=false)
trace: HunkApplier::set_original_newline_status: original_ends_with_newline=true
debug: apply_hunk_to_lines: applying hunk with 7 line(s) against target with 1271 line(s)
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:   Match block: ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/scc.h>", "#include <linux/serial.h>", "#include <linux/sockios.h>", "#include <linux/termios.h>"]
trace: Hunk::get_replace_block: extracted 6 replacement line(s)
trace:   Replace block: ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/serial.h>", "#include <linux/sockios.h>", "#include <linux/termios.h>"]
trace: Hunk::has_changes: true
trace: Hunk::get_match_block: extracted 7 match line(s)
trace: Hunk::required_match_span: calculated required match span as 1 line(s) (first_match_idx=Some(3), last_match_idx=Some(3))
trace: DefaultHunkFinder::find_candidate_locations: match block len=7, required_match_span=1, target lines=1271
trace:   find_hunk_location_internal: match_block has 7 lines (entropy=true), target has 1271 lines
trace:   find_hunk_location_internal called for a hunk with 7 lines to match against 1271 target lines.
trace:     Attempting exact match for hunk (match block has 7 line(s))...
trace: tie_break_with_line_number: strategy='exact', hint=Some(153), entropy=true
trace:       No exact matches found.
trace:     Strategy 1 (Exact): no exact match found.
trace:     Attempting exact match (ignoring trailing whitespace) for hunk (match block has 7 line(s))...
trace: tie_break_with_line_number: strategy='exact (ignoring whitespace)', hint=Some(153), entropy=true
trace:       No exact (ignoring whitespace) matches found.
trace:     Strategy 2 (Whitespace-insensitive): no match found.
debug:     Strategy 3 (Fuzzy): beginning flexible window fuzzy search (threshold=0.70, match block len=0.7)
trace:       Hunk match block (7 lines): ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/scc.h>", "#include <linux/serial.h>", "#include <linux/sockios.h>", "#include <linux/termios.h>"]
trace:       Searching with window sizes from 2 to 30 (hunk size: 7, fuzz distance: 23)
debug:       find_search_ranges: analyzing 7 match line(s) against 1271 target line(s).
trace:         Identified 7 high-entropy candidate anchor line(s) (search_radius=15, max candidates to test=100)
debug:         Spatial consensus: 5 anchor(s) agree on start near line 163
debug:       Found anchor line (hunk line 1) with 1 occurrences.
trace:         Anchor text: '#include <linux/cyclades.h>'
trace:         Occurrence at target line 153: window estimated [138..197] (search radius +/-15)
trace:         Raw ranges before merging: [(137, 197)]
trace: merge_ranges: merging 1 input range(s): [(137, 197)]
trace: merge_ranges: result 1 disjoint range(s): [(137, 197)]
debug:       Search ranges merged: 1 disjoint range(s) covering 60/1271 line(s) (95.3% pruned): [(137, 197)]
trace:     Using search ranges: [(137, 197)]
debug:       compute_scored_windows (parallel): evaluating 1305 candidate window(s) across 1 range(s) (window lengths 2..=30)
trace:         Match block length: 7, Target line count: 1271, Search ranges: [(137, 197)]
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.208
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.383
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.299
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.275
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.437
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.492
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.334
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.387
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.369
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.350
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.424
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.324
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.418
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.317
trace:         score_window: window_len=18, match_len=7, line_score=0.395, ratio_lines=0.240, final_score=0.395
trace:         score_window: window_len=19, match_len=7, line_score=0.392, ratio_lines=0.231, final_score=0.392
trace:         score_window: window_len=20, match_len=7, line_score=0.389, ratio_lines=0.222, final_score=0.389
trace:         score_window: window_len=21, match_len=7, line_score=0.386, ratio_lines=0.214, final_score=0.386
trace:         score_window: window_len=22, match_len=7, line_score=0.510, ratio_lines=0.276, final_score=0.510
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.379
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.290
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.220
trace:         score_window: window_len=15, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.359
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.458
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.516
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.425
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.351
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.429
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.422
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.406
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.391
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.369
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.403
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.378
trace:         score_window: window_len=15, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.411
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.341
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.377
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.410
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.403
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.384
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.332
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.317
trace:         score_window: window_len=17, match_len=7, line_score=0.398, ratio_lines=0.250, final_score=0.398
trace:         score_window: window_len=18, match_len=7, line_score=0.395, ratio_lines=0.240, final_score=0.395
trace:         score_window: window_len=19, match_len=7, line_score=0.392, ratio_lines=0.231, final_score=0.392
trace:         score_window: window_len=20, match_len=7, line_score=0.389, ratio_lines=0.222, final_score=0.389
trace:         score_window: window_len=21, match_len=7, line_score=0.514, ratio_lines=0.286, final_score=0.514
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.390
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.367
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.303
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.410
trace:         score_window: window_len=15, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.422
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.424
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.429
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.403
trace:         score_window: window_len=16, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.422
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.369
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.415
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.407
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.359
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.386
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.341
trace:         score_window: window_len=14, match_len=7, line_score=0.136, ratio_lines=0.095, final_score=0.136
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.401
trace:         score_window: window_len=16, match_len=7, line_score=0.401, ratio_lines=0.261, final_score=0.401
trace:         score_window: window_len=17, match_len=7, line_score=0.398, ratio_lines=0.250, final_score=0.398
trace:         score_window: window_len=18, match_len=7, line_score=0.395, ratio_lines=0.240, final_score=0.395
trace:         score_window: window_len=19, match_len=7, line_score=0.392, ratio_lines=0.231, final_score=0.392
trace:         score_window: window_len=20, match_len=7, line_score=0.518, ratio_lines=0.296, final_score=0.518
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.403
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.422
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.459
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.459
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.429
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.434
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.391
trace:         score_window: window_len=15, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.434
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.380
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.423
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.415
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.359
trace:         score_window: window_len=13, match_len=7, line_score=0.137, ratio_lines=0.100, final_score=0.191
trace:         score_window: window_len=14, match_len=7, line_score=0.271, ratio_lines=0.190, final_score=0.271
trace:         score_window: window_len=15, match_len=7, line_score=0.404, ratio_lines=0.273, final_score=0.404
trace:         score_window: window_len=16, match_len=7, line_score=0.401, ratio_lines=0.261, final_score=0.401
trace:         score_window: window_len=17, match_len=7, line_score=0.398, ratio_lines=0.250, final_score=0.398
trace:         score_window: window_len=18, match_len=7, line_score=0.395, ratio_lines=0.240, final_score=0.395
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.393
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.408
trace:         score_window: window_len=19, match_len=7, line_score=0.522, ratio_lines=0.308, final_score=0.522
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.409
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.429
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.441
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.441
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.485
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.423
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.431
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.450
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.406
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.394
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.408
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.371
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.416
trace:         score_window: window_len=12, match_len=7, line_score=0.138, ratio_lines=0.105, final_score=0.138
trace:         score_window: window_len=13, match_len=7, line_score=0.273, ratio_lines=0.200, final_score=0.273
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.429
trace:         score_window: window_len=14, match_len=7, line_score=0.407, ratio_lines=0.286, final_score=0.407
trace:         score_window: window_len=15, match_len=7, line_score=0.404, ratio_lines=0.273, final_score=0.404
trace:         score_window: window_len=16, match_len=7, line_score=0.401, ratio_lines=0.261, final_score=0.401
trace:         score_window: window_len=17, match_len=7, line_score=0.398, ratio_lines=0.250, final_score=0.398
trace:         score_window: window_len=18, match_len=7, line_score=0.527, ratio_lines=0.320, final_score=0.527
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.441
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.441
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.493
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.476
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.404
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.432
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.397
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.443
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.429
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.450
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.424
trace:         score_window: window_len=11, match_len=7, line_score=0.139, ratio_lines=0.111, final_score=0.433
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.462
trace:         score_window: window_len=12, match_len=7, line_score=0.276, ratio_lines=0.211, final_score=0.276
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.462
trace:         score_window: window_len=13, match_len=7, line_score=0.410, ratio_lines=0.300, final_score=0.410
trace:         score_window: window_len=14, match_len=7, line_score=0.407, ratio_lines=0.286, final_score=0.407
trace:         score_window: window_len=15, match_len=7, line_score=0.404, ratio_lines=0.273, final_score=0.404
trace:         score_window: window_len=16, match_len=7, line_score=0.401, ratio_lines=0.261, final_score=0.401
trace:         score_window: window_len=17, match_len=7, line_score=0.531, ratio_lines=0.333, final_score=0.531
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.439
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.419
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.450
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.363
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.448
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.434
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.440
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.384
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.453
trace:         score_window: window_len=10, match_len=7, line_score=0.140, ratio_lines=0.118, final_score=0.460
trace:         score_window: window_len=11, match_len=7, line_score=0.278, ratio_lines=0.222, final_score=0.278
trace:         score_window: window_len=12, match_len=7, line_score=0.413, ratio_lines=0.316, final_score=0.413
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.453
trace:         score_window: window_len=13, match_len=7, line_score=0.410, ratio_lines=0.300, final_score=0.420
trace:         score_window: window_len=14, match_len=7, line_score=0.407, ratio_lines=0.286, final_score=0.407
trace:         score_window: window_len=15, match_len=7, line_score=0.404, ratio_lines=0.273, final_score=0.407
trace:         score_window: window_len=16, match_len=7, line_score=0.535, ratio_lines=0.348, final_score=0.535
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.429
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.315
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.415
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.431
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.370
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.367
trace:         score_window: window_len=9, match_len=7, line_score=0.141, ratio_lines=0.125, final_score=0.421
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.399
trace:         score_window: window_len=10, match_len=7, line_score=0.280, ratio_lines=0.235, final_score=0.280
trace:         score_window: window_len=11, match_len=7, line_score=0.416, ratio_lines=0.333, final_score=0.416
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.413
trace:         score_window: window_len=12, match_len=7, line_score=0.413, ratio_lines=0.316, final_score=0.440
trace:         score_window: window_len=13, match_len=7, line_score=0.410, ratio_lines=0.300, final_score=0.507
trace:         score_window: window_len=14, match_len=7, line_score=0.407, ratio_lines=0.286, final_score=0.427
trace:         score_window: window_len=15, match_len=7, line_score=0.539, ratio_lines=0.364, final_score=0.539
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.413
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.395
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.389
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.364
trace:         score_window: window_len=8, match_len=7, line_score=0.142, ratio_lines=0.133, final_score=0.378
trace:         score_window: window_len=9, match_len=7, line_score=0.282, ratio_lines=0.250, final_score=0.282
trace:         score_window: window_len=10, match_len=7, line_score=0.419, ratio_lines=0.353, final_score=0.419
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.334
trace:         score_window: window_len=11, match_len=7, line_score=0.416, ratio_lines=0.333, final_score=0.461
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.349
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.249
trace:         score_window: window_len=12, match_len=7, line_score=0.413, ratio_lines=0.316, final_score=0.529
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.366
trace:         score_window: window_len=13, match_len=7, line_score=0.410, ratio_lines=0.300, final_score=0.572
trace:         score_window: window_len=14, match_len=7, line_score=0.543, ratio_lines=0.381, final_score=0.543
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.366
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.355
trace:         score_window: window_len=7, match_len=7, line_score=0.143, ratio_lines=0.143, final_score=0.328
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.389
trace:         score_window: window_len=8, match_len=7, line_score=0.284, ratio_lines=0.267, final_score=0.298
trace:         score_window: window_len=9, match_len=7, line_score=0.422, ratio_lines=0.375, final_score=0.422
trace:         score_window: window_len=10, match_len=7, line_score=0.419, ratio_lines=0.353, final_score=0.484
trace:         score_window: window_len=11, match_len=7, line_score=0.416, ratio_lines=0.333, final_score=0.554
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.320
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.345
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.345
trace:         score_window: window_len=12, match_len=7, line_score=0.413, ratio_lines=0.316, final_score=0.598
trace:         score_window: window_len=13, match_len=7, line_score=0.547, ratio_lines=0.400, final_score=0.547
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.337
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.302
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.322
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.322
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.286, ratio_lines=0.286, final_score=0.320
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.361
trace:         score_window: window_len=6, match_len=7, line_score=0.154, ratio_lines=0.154, final_score=0.281
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.321
trace:         score_window: window_len=8, match_len=7, line_score=0.426, ratio_lines=0.400, final_score=0.444
trace:         score_window: window_len=9, match_len=7, line_score=0.422, ratio_lines=0.375, final_score=0.515
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.340
trace:         score_window: window_len=10, match_len=7, line_score=0.419, ratio_lines=0.353, final_score=0.588
trace:         score_window: window_len=11, match_len=7, line_score=0.416, ratio_lines=0.333, final_score=0.632
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.340
trace:         score_window: window_len=12, match_len=7, line_score=0.551, ratio_lines=0.421, final_score=0.561
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.340
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.361
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.321
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.340
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.340
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.340
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.336
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.380
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.354
trace:         score_window: window_len=7, match_len=7, line_score=0.429, ratio_lines=0.429, final_score=0.474
trace:         score_window: window_len=6, match_len=7, line_score=0.308, ratio_lines=0.308, final_score=0.343
trace:         score_window: window_len=8, match_len=7, line_score=0.426, ratio_lines=0.400, final_score=0.548
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.354
trace:         score_window: window_len=9, match_len=7, line_score=0.422, ratio_lines=0.375, final_score=0.622
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.354
trace:         score_window: window_len=10, match_len=7, line_score=0.419, ratio_lines=0.353, final_score=0.667
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.313
trace:         score_window: window_len=11, match_len=7, line_score=0.555, ratio_lines=0.444, final_score=0.593
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.276
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.313
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.317
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.282
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.288
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.264
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.264
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.278
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.211
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.429, ratio_lines=0.429, final_score=0.583
trace:         score_window: window_len=6, match_len=7, line_score=0.462, ratio_lines=0.462, final_score=0.507
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.268
trace:         score_window: window_len=8, match_len=7, line_score=0.426, ratio_lines=0.400, final_score=0.660
trace:         score_window: window_len=5, match_len=7, line_score=0.333, ratio_lines=0.333, final_score=0.333
trace:         score_window: window_len=9, match_len=7, line_score=0.422, ratio_lines=0.375, final_score=0.704
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.307
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.293
trace:         score_window: window_len=10, match_len=7, line_score=0.559, ratio_lines=0.471, final_score=0.629
trace:         score_window: window_len=11, match_len=7, line_score=0.694, ratio_lines=0.556, final_score=0.694
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.292
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.293
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.280
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.236
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.429, ratio_lines=0.429, final_score=0.706
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.243
trace:         score_window: window_len=6, match_len=7, line_score=0.462, ratio_lines=0.462, final_score=0.628
trace:         score_window: window_len=8, match_len=7, line_score=0.426, ratio_lines=0.400, final_score=0.749
trace:         score_window: window_len=5, match_len=7, line_score=0.500, ratio_lines=0.500, final_score=0.548
trace:         score_window: window_len=9, match_len=7, line_score=0.563, ratio_lines=0.500, final_score=0.687
trace:         score_window: window_len=4, match_len=7, line_score=0.364, ratio_lines=0.364, final_score=0.364
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.229
trace:         score_window: window_len=10, match_len=7, line_score=0.699, ratio_lines=0.588, final_score=0.699
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.224
trace:         score_window: window_len=11, match_len=7, line_score=0.694, ratio_lines=0.556, final_score=0.694
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.224
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.229
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.236
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.243
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.224
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=3, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.224
trace:         score_window: window_len=7, match_len=7, line_score=0.429, ratio_lines=0.429, final_score=0.765
trace:         score_window: window_len=6, match_len=7, line_score=0.462, ratio_lines=0.462, final_score=0.722
trace:         score_window: window_len=8, match_len=7, line_score=0.567, ratio_lines=0.533, final_score=0.715
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.268
trace:         score_window: window_len=5, match_len=7, line_score=0.500, ratio_lines=0.500, final_score=0.644
trace:         score_window: window_len=4, match_len=7, line_score=0.545, ratio_lines=0.545, final_score=0.545
trace:         score_window: window_len=10, match_len=7, line_score=0.699, ratio_lines=0.588, final_score=0.699
trace:         score_window: window_len=3, match_len=7, line_score=0.400, ratio_lines=0.400, final_score=0.400
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.280
trace:         score_window: window_len=11, match_len=7, line_score=0.694, ratio_lines=0.556, final_score=0.694
trace:         score_window: window_len=2, match_len=7, line_score=0.222, ratio_lines=0.222, final_score=0.273
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.284
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.227
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.219
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.225
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.243
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.571, ratio_lines=0.571, final_score=0.768
trace:         score_window: window_len=6, match_len=7, line_score=0.462, ratio_lines=0.462, final_score=0.814
trace:         score_window: window_len=5, match_len=7, line_score=0.500, ratio_lines=0.500, final_score=0.772
trace:         score_window: window_len=4, match_len=7, line_score=0.545, ratio_lines=0.545, final_score=0.630
trace:         score_window: window_len=10, match_len=7, line_score=0.699, ratio_lines=0.588, final_score=0.707
trace:         score_window: window_len=3, match_len=7, line_score=0.600, ratio_lines=0.600, final_score=0.600
trace:         score_window: window_len=11, match_len=7, line_score=0.694, ratio_lines=0.556, final_score=0.694
trace:         score_window: window_len=2, match_len=7, line_score=0.444, ratio_lines=0.444, final_score=0.444
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.207
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.217
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.230
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.238
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.210
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.220
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.210
trace:         score_window: window_len=3, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.215
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.200
trace:         score_window: window_len=7, match_len=7, line_score=0.571, ratio_lines=0.571, final_score=0.571
trace:         score_window: window_len=6, match_len=7, line_score=0.462, ratio_lines=0.462, final_score=0.670
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.208
trace:         score_window: window_len=8, match_len=7, line_score=0.567, ratio_lines=0.533, final_score=0.611
trace:         score_window: window_len=5, match_len=7, line_score=0.333, ratio_lines=0.333, final_score=0.708
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.219
trace:         score_window: window_len=3, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.181
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.200
trace:         score_window: window_len=9, match_len=7, line_score=0.563, ratio_lines=0.500, final_score=0.642
trace:         score_window: window_len=4, match_len=7, line_score=0.364, ratio_lines=0.364, final_score=0.542
trace:         score_window: window_len=10, match_len=7, line_score=0.559, ratio_lines=0.471, final_score=0.577
trace:         score_window: window_len=3, match_len=7, line_score=0.400, ratio_lines=0.400, final_score=0.488
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.208
trace:         score_window: window_len=11, match_len=7, line_score=0.555, ratio_lines=0.444, final_score=0.575
trace:         score_window: window_len=2, match_len=7, line_score=0.444, ratio_lines=0.444, final_score=0.444
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.219
trace:         score_window: window_len=3, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.207
trace:         score_window: window_len=12, match_len=7, line_score=0.551, ratio_lines=0.421, final_score=0.551
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.200
trace:         score_window: window_len=13, match_len=7, line_score=0.547, ratio_lines=0.400, final_score=0.547
trace:         score_window: window_len=14, match_len=7, line_score=0.543, ratio_lines=0.381, final_score=0.543
trace:         score_window: window_len=15, match_len=7, line_score=0.539, ratio_lines=0.364, final_score=0.539
trace:         score_window: window_len=16, match_len=7, line_score=0.535, ratio_lines=0.348, final_score=0.535
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.208
trace:         score_window: window_len=17, match_len=7, line_score=0.531, ratio_lines=0.333, final_score=0.531
trace:         score_window: window_len=18, match_len=7, line_score=0.527, ratio_lines=0.320, final_score=0.527
trace:         score_window: window_len=19, match_len=7, line_score=0.522, ratio_lines=0.308, final_score=0.522
trace:         score_window: window_len=20, match_len=7, line_score=0.518, ratio_lines=0.296, final_score=0.518
trace:         score_window: window_len=21, match_len=7, line_score=0.514, ratio_lines=0.286, final_score=0.514
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.219
trace:         score_window: window_len=3, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.207
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.203
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.212
trace:         score_window: window_len=3, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.200
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.212
trace:         score_window: window_len=3, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.200
trace:         score_window: window_len=3, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.200
trace:         score_window: window_len=22, match_len=7, line_score=0.510, ratio_lines=0.276, final_score=0.510
trace:         score_window: window_len=23, match_len=7, line_score=0.506, ratio_lines=0.267, final_score=0.506
trace:         score_window: window_len=7, match_len=7, line_score=0.286, ratio_lines=0.286, final_score=0.444
trace:         score_window: window_len=24, match_len=7, line_score=0.502, ratio_lines=0.258, final_score=0.502
trace:         score_window: window_len=25, match_len=7, line_score=0.498, ratio_lines=0.250, final_score=0.498
trace:         score_window: window_len=6, match_len=7, line_score=0.308, ratio_lines=0.308, final_score=0.475
trace:         score_window: window_len=26, match_len=7, line_score=0.494, ratio_lines=0.242, final_score=0.494
trace:         score_window: window_len=27, match_len=7, line_score=0.490, ratio_lines=0.235, final_score=0.490
trace:         score_window: window_len=8, match_len=7, line_score=0.284, ratio_lines=0.267, final_score=0.439
trace:         score_window: window_len=28, match_len=7, line_score=0.486, ratio_lines=0.229, final_score=0.486
trace:         score_window: window_len=5, match_len=7, line_score=0.333, ratio_lines=0.333, final_score=0.477
trace:         score_window: window_len=29, match_len=7, line_score=0.482, ratio_lines=0.222, final_score=0.482
trace:         score_window: window_len=30, match_len=7, line_score=0.478, ratio_lines=0.216, final_score=0.478
trace:         score_window: window_len=9, match_len=7, line_score=0.282, ratio_lines=0.250, final_score=0.452
trace:         score_window: window_len=4, match_len=7, line_score=0.364, ratio_lines=0.364, final_score=0.542
trace:         score_window: window_len=10, match_len=7, line_score=0.280, ratio_lines=0.235, final_score=0.427
trace:         score_window: window_len=3, match_len=7, line_score=0.400, ratio_lines=0.400, final_score=0.488
trace:         score_window: window_len=11, match_len=7, line_score=0.278, ratio_lines=0.222, final_score=0.402
trace:         score_window: window_len=2, match_len=7, line_score=0.444, ratio_lines=0.444, final_score=0.444
trace:         score_window: window_len=12, match_len=7, line_score=0.276, ratio_lines=0.211, final_score=0.395
trace:         score_window: window_len=7, match_len=7, line_score=0.429, ratio_lines=0.429, final_score=0.696
trace:         score_window: window_len=6, match_len=7, line_score=0.462, ratio_lines=0.462, final_score=0.652
trace:         score_window: window_len=8, match_len=7, line_score=0.426, ratio_lines=0.400, final_score=0.725
trace:         score_window: window_len=5, match_len=7, line_score=0.333, ratio_lines=0.333, final_score=0.557
trace:         score_window: window_len=13, match_len=7, line_score=0.273, ratio_lines=0.200, final_score=0.394
trace:         score_window: window_len=9, match_len=7, line_score=0.422, ratio_lines=0.375, final_score=0.647
trace:         score_window: window_len=10, match_len=7, line_score=0.419, ratio_lines=0.353, final_score=0.645
trace:         score_window: window_len=11, match_len=7, line_score=0.416, ratio_lines=0.333, final_score=0.613
trace:         score_window: window_len=2, match_len=7, line_score=0.222, ratio_lines=0.222, final_score=0.314
trace:         score_window: window_len=14, match_len=7, line_score=0.271, ratio_lines=0.190, final_score=0.377
trace:         score_window: window_len=12, match_len=7, line_score=0.413, ratio_lines=0.316, final_score=0.601
trace:         score_window: window_len=15, match_len=7, line_score=0.269, ratio_lines=0.182, final_score=0.368
trace:         score_window: window_len=13, match_len=7, line_score=0.410, ratio_lines=0.300, final_score=0.603
trace:         score_window: window_len=14, match_len=7, line_score=0.407, ratio_lines=0.286, final_score=0.452
trace:         score_window: window_len=15, match_len=7, line_score=0.404, ratio_lines=0.273, final_score=0.432
trace:         score_window: window_len=16, match_len=7, line_score=0.401, ratio_lines=0.261, final_score=0.420
trace:         score_window: window_len=17, match_len=7, line_score=0.398, ratio_lines=0.250, final_score=0.413
trace:         score_window: window_len=18, match_len=7, line_score=0.395, ratio_lines=0.240, final_score=0.400
trace:         score_window: window_len=19, match_len=7, line_score=0.392, ratio_lines=0.231, final_score=0.392
trace:         score_window: window_len=20, match_len=7, line_score=0.389, ratio_lines=0.222, final_score=0.389
trace:         score_window: window_len=7, match_len=7, line_score=0.143, ratio_lines=0.143, final_score=0.334
trace:         score_window: window_len=21, match_len=7, line_score=0.386, ratio_lines=0.214, final_score=0.386
trace:         score_window: window_len=7, match_len=7, line_score=0.286, ratio_lines=0.286, final_score=0.750
trace:         score_window: window_len=6, match_len=7, line_score=0.154, ratio_lines=0.154, final_score=0.333
trace:         score_window: window_len=6, match_len=7, line_score=0.308, ratio_lines=0.308, final_score=0.720
trace:         score_window: window_len=8, match_len=7, line_score=0.142, ratio_lines=0.133, final_score=0.355
trace:         score_window: window_len=8, match_len=7, line_score=0.284, ratio_lines=0.267, final_score=0.663
trace:         score_window: window_len=5, match_len=7, line_score=0.167, ratio_lines=0.167, final_score=0.357
trace:         score_window: window_len=5, match_len=7, line_score=0.333, ratio_lines=0.333, final_score=0.673
trace:         score_window: window_len=9, match_len=7, line_score=0.141, ratio_lines=0.125, final_score=0.335
trace:         score_window: window_len=9, match_len=7, line_score=0.282, ratio_lines=0.250, final_score=0.661
trace:         score_window: window_len=10, match_len=7, line_score=0.280, ratio_lines=0.235, final_score=0.627
trace:         score_window: window_len=11, match_len=7, line_score=0.278, ratio_lines=0.222, final_score=0.613
trace:         score_window: window_len=4, match_len=7, line_score=0.182, ratio_lines=0.182, final_score=0.359
trace:         score_window: window_len=12, match_len=7, line_score=0.276, ratio_lines=0.211, final_score=0.615
trace:         score_window: window_len=10, match_len=7, line_score=0.140, ratio_lines=0.118, final_score=0.226
trace:         score_window: window_len=7, match_len=7, line_score=0.286, ratio_lines=0.286, final_score=0.613
trace:         score_window: window_len=11, match_len=7, line_score=0.139, ratio_lines=0.111, final_score=0.245
trace:         score_window: window_len=2, match_len=7, line_score=0.222, ratio_lines=0.222, final_score=0.314
trace:         score_window: window_len=6, match_len=7, line_score=0.308, ratio_lines=0.308, final_score=0.698
trace:         score_window: window_len=8, match_len=7, line_score=0.284, ratio_lines=0.267, final_score=0.611
trace:         score_window: window_len=12, match_len=7, line_score=0.138, ratio_lines=0.105, final_score=0.244
trace:         score_window: window_len=5, match_len=7, line_score=0.333, ratio_lines=0.333, final_score=0.663
trace:         score_window: window_len=9, match_len=7, line_score=0.282, ratio_lines=0.250, final_score=0.577
trace:         score_window: window_len=4, match_len=7, line_score=0.364, ratio_lines=0.364, final_score=0.542
trace:         score_window: window_len=13, match_len=7, line_score=0.137, ratio_lines=0.100, final_score=0.233
trace:         score_window: window_len=10, match_len=7, line_score=0.280, ratio_lines=0.235, final_score=0.566
trace:         score_window: window_len=14, match_len=7, line_score=0.136, ratio_lines=0.095, final_score=0.262
trace:         score_window: window_len=11, match_len=7, line_score=0.278, ratio_lines=0.222, final_score=0.571
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.275
trace:         score_window: window_len=12, match_len=7, line_score=0.276, ratio_lines=0.211, final_score=0.541
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.215
trace:         score_window: window_len=7, match_len=7, line_score=0.286, ratio_lines=0.286, final_score=0.550
trace:         score_window: window_len=6, match_len=7, line_score=0.308, ratio_lines=0.308, final_score=0.552
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.327
trace:         score_window: window_len=8, match_len=7, line_score=0.284, ratio_lines=0.267, final_score=0.518
trace:         score_window: window_len=5, match_len=7, line_score=0.333, ratio_lines=0.333, final_score=0.635
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.372
trace:         score_window: window_len=9, match_len=7, line_score=0.282, ratio_lines=0.250, final_score=0.509
trace:         score_window: window_len=4, match_len=7, line_score=0.364, ratio_lines=0.364, final_score=0.542
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.382
trace:         score_window: window_len=10, match_len=7, line_score=0.280, ratio_lines=0.235, final_score=0.517
trace:         score_window: window_len=3, match_len=7, line_score=0.400, ratio_lines=0.400, final_score=0.488
trace:         score_window: window_len=11, match_len=7, line_score=0.278, ratio_lines=0.222, final_score=0.489
trace:         score_window: window_len=2, match_len=7, line_score=0.222, ratio_lines=0.222, final_score=0.314
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.376
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.380
trace:         score_window: window_len=12, match_len=7, line_score=0.276, ratio_lines=0.211, final_score=0.462
trace:         score_window: window_len=13, match_len=7, line_score=0.273, ratio_lines=0.200, final_score=0.455
trace:         score_window: window_len=14, match_len=7, line_score=0.271, ratio_lines=0.190, final_score=0.454
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.325
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.378
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.359
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.359
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.338
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.338
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.356
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.339
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.339
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.239
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.380
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.327
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.391
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.339
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.341
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.356
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.387
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.339
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.420
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.396
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.340
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.393
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.378
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.436
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.438
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.374
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.429
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.386
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.408
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.355
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.404
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.396
trace:         score_window: window_len=15, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.350
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.443
trace:         score_window: window_len=16, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.337
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.379
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.377
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.438
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.425
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.391
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.438
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.359
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.394
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.378
trace:         score_window: window_len=15, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.362
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.355
trace:         score_window: window_len=15, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.341
debug:       compute_scored_windows (parallel) complete: scored 1305 window(s). Best candidate score=0.814 at line 153 (len=6).
trace:       Top fuzzy match candidates:
trace:         - Index 152, Len 6: Score 0.814 (Ratio 0.814) | Content: ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>"]
trace:         - Index 152, Len 5: Score 0.772 (Ratio 0.772) | Content: ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>"]
trace:         - Index 152, Len 7: Score 0.768 (Ratio 0.768) | Content: ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>", "#include <linux/scc.h>"]
trace:         - Index 151, Len 7: Score 0.765 (Ratio 0.765) | Content: ["#include <sys/user.h>", "#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>"]
trace:         - Index 155, Len 7: Score 0.750 (Ratio 0.750) | Content: ["#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>", "#include <linux/scc.h>", "#include <linux/serial.h>", "#include <sys/msg.h>", "#include <sys/ipc.h>"]
trace:         New best score: 0.208 (ratio 0.208 [l:0.000,w:0.250]) at index 137 (window len 7)
trace:         New best score: 0.299 (ratio 0.299 [l:0.000,w:0.154]) at index 137 (window len 6)
trace:         New best score: 0.632 (ratio 0.632 [l:0.000,w:0.000]) at index 137 (window len 5)
trace:         New best score: 0.677 (ratio 0.677 [l:0.000,w:0.000]) at index 137 (window len 15)
trace:         New best score: 0.695 (ratio 0.695 [l:0.000,w:0.000]) at index 141 (window len 6)
trace:         New best score: 0.704 (ratio 0.704 [l:0.375,w:0.645]) at index 149 (window len 9)
trace:         New best score: 0.706 (ratio 0.706 [l:0.429,w:0.654]) at index 150 (window len 7)
trace:         New best score: 0.749 (ratio 0.749 [l:0.400,w:0.714]) at index 150 (window len 8)
trace:         New best score: 0.765 (ratio 0.765 [l:0.429,w:0.741]) at index 151 (window len 7)
trace:         New best score: 0.768 (ratio 0.768 [l:0.571,w:0.852]) at index 152 (window len 7)
trace:         New best score: 0.814 (ratio 0.814 [l:0.462,w:0.800]) at index 152 (window len 6)
debug:     Strategy 3 (Fuzzy): 17 window(s) met threshold 0.70
trace:       Top 3 passing candidates: [("0.814", 153, 6), ("0.772", 153, 5), ("0.768", 153, 7)]
debug:     Top fuzzy candidate: start line 153 (len=6, score=0.814)
trace:       Adding candidate location at line 153 (len=5, score=0.772)
trace:       Adding candidate location at line 153 (len=7, score=0.768)
trace:       Adding candidate location at line 152 (len=7, score=0.765)
trace:       Adding candidate location at line 156 (len=7, score=0.750)
trace:       Adding candidate location at line 151 (len=8, score=0.749)
trace:       Adding candidate location at line 155 (len=8, score=0.725)
trace:       Adding candidate location at line 152 (len=6, score=0.722)
trace:       Adding candidate location at line 156 (len=6, score=0.720)
trace:       Adding candidate location at line 152 (len=8, score=0.715)
trace:       Adding candidate location at line 153 (len=8, score=0.709)
trace:       Adding candidate location at line 154 (len=5, score=0.708)
trace:       Adding candidate location at line 153 (len=10, score=0.707)
trace:       Adding candidate location at line 151 (len=7, score=0.706)
trace:       Adding candidate location at line 152 (len=9, score=0.704)
trace:       Adding candidate location at line 150 (len=9, score=0.704)
debug:     Strategy 3 (Fuzzy): selected 16 candidate location(s)
trace:   Pruned candidates by min_span 1: 16 -> 16 candidate(s)
trace: DefaultHunkFinder::find_candidate_locations: returning 16 candidate(s)
debug:   Found 16 candidate location(s) for hunk. Testing sequentially...
trace:   Evaluating candidate 1/16 at location HunkLocation { start_index: 152, length: 6 } (match_type: Fuzzy { score: 0.8143066972494126 })
debug:   Found location HunkLocation { start_index: 152, length: 6 } with match type Fuzzy { score: 0.8143066972494126 }. Applying changes.
debug:   try_apply_hunk_at_location: target line 153 (length 6), match_type=Fuzzy { score: 0.8143066972494126 }, total target lines=1271.
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:     Match block lines: 7 | Total hunk lines: 7
trace:     Target slice to replace: ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>"]
trace:     Ellipsis flags: has_ellipsis=false, is_literal_match=false, is_wildcard_gap_match=false
debug:     Applying hunk via robust reconstruction logic (preserving file context & adjusting indent).
trace:       Fuzzy match location: start=152, len=6
trace:       File content in matched range (6 line(s)): ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>"]
trace:       Parsed hunk: 7 match line(s), 0 initial addition(s).
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:       Computed diff between match block and file slice: 2 operation(s), similarity ratio=0.462
trace:       Active baseline indentation: hunk='', target=''
trace:       DiffOp::Equal: 3 line(s) aligned (hunk old_idx=0, file new_idx=0)
trace:         Equal: preserving target line: '#include <linux/cyclades.h>'
trace:         Equal: preserving target line: '#include <linux/if_eql.h>'
trace:         Equal: preserving target line: '#include <linux/if_plip.h>'
trace:       DiffOp::Replace: hunk lines 3..7 (len=4) vs file lines 3..6 (len=3)
trace:         Multi-line replacement (hunk_len=4, target_len=3). Searching for statement alignment across line breaks...
trace: find_statement_match_in_block: attempting statement alignment for 4 line(s) against 3 target line(s)
trace:         No single statement alignment found (has_context=true). Using block fallback heuristic.
warning:     Fuzzy match rejected: Tail context is unaligned in replacement block.
debug:   Candidate 1/16 at HunkLocation { start_index: 152, length: 6 } failed with ContextNotFound. Backtracking...
trace:   Evaluating candidate 2/16 at location HunkLocation { start_index: 152, length: 5 } (match_type: Fuzzy { score: 0.7724913537502289 })
debug:   Found location HunkLocation { start_index: 152, length: 5 } with match type Fuzzy { score: 0.7724913537502289 }. Applying changes.
debug:   try_apply_hunk_at_location: target line 153 (length 5), match_type=Fuzzy { score: 0.7724913537502289 }, total target lines=1271.
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:     Match block lines: 7 | Total hunk lines: 7
trace:     Target slice to replace: ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>"]
trace:     Ellipsis flags: has_ellipsis=false, is_literal_match=false, is_wildcard_gap_match=false
debug:     Applying hunk via robust reconstruction logic (preserving file context & adjusting indent).
trace:       Fuzzy match location: start=152, len=5
trace:       File content in matched range (5 line(s)): ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>"]
trace:       Parsed hunk: 7 match line(s), 0 initial addition(s).
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:       Computed diff between match block and file slice: 2 operation(s), similarity ratio=0.500
trace:       Active baseline indentation: hunk='', target=''
trace:       DiffOp::Equal: 3 line(s) aligned (hunk old_idx=0, file new_idx=0)
trace:         Equal: preserving target line: '#include <linux/cyclades.h>'
trace:         Equal: preserving target line: '#include <linux/if_eql.h>'
trace:         Equal: preserving target line: '#include <linux/if_plip.h>'
trace:       DiffOp::Replace: hunk lines 3..7 (len=4) vs file lines 3..5 (len=2)
trace:         Multi-line replacement (hunk_len=4, target_len=2). Searching for statement alignment across line breaks...
trace: find_statement_match_in_block: attempting statement alignment for 4 line(s) against 2 target line(s)
trace:         No single statement alignment found (has_context=true). Using block fallback heuristic.
warning:     Fuzzy match rejected: Tail context is unaligned in replacement block.
debug:   Candidate 2/16 at HunkLocation { start_index: 152, length: 5 } failed with ContextNotFound. Backtracking...
trace:   Evaluating candidate 3/16 at location HunkLocation { start_index: 152, length: 7 } (match_type: Fuzzy { score: 0.7677248954772948 })
debug:   Found location HunkLocation { start_index: 152, length: 7 } with match type Fuzzy { score: 0.7677248954772948 }. Applying changes.
debug:   try_apply_hunk_at_location: target line 153 (length 7), match_type=Fuzzy { score: 0.7677248954772948 }, total target lines=1271.
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:     Match block lines: 7 | Total hunk lines: 7
trace:     Target slice to replace: ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>", "#include <linux/scc.h>"]
trace:     Ellipsis flags: has_ellipsis=false, is_literal_match=false, is_wildcard_gap_match=false
debug:     Applying hunk via robust reconstruction logic (preserving file context & adjusting indent).
trace:       Fuzzy match location: start=152, len=7
trace:       File content in matched range (7 line(s)): ["#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>", "#include <linux/scc.h>"]
trace:       Parsed hunk: 7 match line(s), 0 initial addition(s).
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:       Computed diff between match block and file slice: 4 operation(s), similarity ratio=0.571
trace:       Active baseline indentation: hunk='', target=''
trace:       DiffOp::Equal: 3 line(s) aligned (hunk old_idx=0, file new_idx=0)
trace:         Equal: preserving target line: '#include <linux/cyclades.h>'
trace:         Equal: preserving target line: '#include <linux/if_eql.h>'
trace:         Equal: preserving target line: '#include <linux/if_plip.h>'
trace:       DiffOp::Insert: preserving 3 local insertion line(s) from target file (new_idx=3)
trace:         Preserving inserted line: '#include <linux/lp.h>'
trace:         Preserving inserted line: '#include <linux/mroute.h>'
trace:         Preserving inserted line: '#include <linux/mroute6.h>'
trace:       DiffOp::Equal: 1 line(s) aligned (hunk old_idx=3, file new_idx=6)
trace:         Equal: removing target line: '#include <linux/scc.h>'
trace:       DiffOp::Delete: 3 line(s) missing from target file (hunk old_idx=4)
warning:     Fuzzy match rejected: Tail context line(s) missing from target file.
debug:   Candidate 3/16 at HunkLocation { start_index: 152, length: 7 } failed with ContextNotFound. Backtracking...
trace:   Evaluating candidate 4/16 at location HunkLocation { start_index: 151, length: 7 } (match_type: Fuzzy { score: 0.7650128453969957 })
debug:   Found location HunkLocation { start_index: 151, length: 7 } with match type Fuzzy { score: 0.7650128453969957 }. Applying changes.
debug:   try_apply_hunk_at_location: target line 152 (length 7), match_type=Fuzzy { score: 0.7650128453969957 }, total target lines=1271.
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:     Match block lines: 7 | Total hunk lines: 7
trace:     Target slice to replace: ["#include <sys/user.h>", "#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>"]
trace:     Ellipsis flags: has_ellipsis=false, is_literal_match=false, is_wildcard_gap_match=false
debug:     Applying hunk via robust reconstruction logic (preserving file context & adjusting indent).
trace:       Fuzzy match location: start=151, len=7
trace:       File content in matched range (7 line(s)): ["#include <sys/user.h>", "#include <linux/cyclades.h>", "#include <linux/if_eql.h>", "#include <linux/if_plip.h>", "#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>"]
trace:       Parsed hunk: 7 match line(s), 0 initial addition(s).
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:       Computed diff between match block and file slice: 3 operation(s), similarity ratio=0.429
trace:       Active baseline indentation: hunk='', target=''
trace:       DiffOp::Insert: preserving 1 local insertion line(s) from target file (new_idx=0)
trace:         Preserving inserted line: '#include <sys/user.h>'
trace:       DiffOp::Equal: 3 line(s) aligned (hunk old_idx=0, file new_idx=1)
trace:         Equal: preserving target line: '#include <linux/cyclades.h>'
trace:         Equal: preserving target line: '#include <linux/if_eql.h>'
trace:         Equal: preserving target line: '#include <linux/if_plip.h>'
trace:       DiffOp::Replace: hunk lines 3..7 (len=4) vs file lines 4..7 (len=3)
trace:         Multi-line replacement (hunk_len=4, target_len=3). Searching for statement alignment across line breaks...
trace: find_statement_match_in_block: attempting statement alignment for 4 line(s) against 3 target line(s)
trace:         No single statement alignment found (has_context=true). Using block fallback heuristic.
warning:     Fuzzy match rejected: Tail context is unaligned in replacement block.
debug:   Candidate 4/16 at HunkLocation { start_index: 151, length: 7 } failed with ContextNotFound. Backtracking...
trace:   Evaluating candidate 5/16 at location HunkLocation { start_index: 155, length: 7 } (match_type: Fuzzy { score: 0.7496894389390946 })
debug:   Found location HunkLocation { start_index: 155, length: 7 } with match type Fuzzy { score: 0.7496894389390946 }. Applying changes.
debug:   try_apply_hunk_at_location: target line 156 (length 7), match_type=Fuzzy { score: 0.7496894389390946 }, total target lines=1271.
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:     Match block lines: 7 | Total hunk lines: 7
trace:     Target slice to replace: ["#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>", "#include <linux/scc.h>", "#include <linux/serial.h>", "#include <sys/msg.h>", "#include <sys/ipc.h>"]
trace:     Ellipsis flags: has_ellipsis=false, is_literal_match=false, is_wildcard_gap_match=false
debug:     Applying hunk via robust reconstruction logic (preserving file context & adjusting indent).
trace:       Fuzzy match location: start=155, len=7
trace:       File content in matched range (7 line(s)): ["#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>", "#include <linux/scc.h>", "#include <linux/serial.h>", "#include <sys/msg.h>", "#include <sys/ipc.h>"]
trace:       Parsed hunk: 7 match line(s), 0 initial addition(s).
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:       Computed diff between match block and file slice: 3 operation(s), similarity ratio=0.286
trace:       Active baseline indentation: hunk='', target=''
trace:       DiffOp::Replace: hunk lines 0..3 (len=3) vs file lines 0..3 (len=3)
trace:         1-to-1 length replacement. Validating similarity of modified lines...
trace:         1-to-1 replacement line validation [line 0]: is_removal=false, word_sim=0.667, char_sim=0.826
trace:         Replace (1-to-1): preserving context line: '#include <linux/lp.h>'
trace:         1-to-1 replacement line validation [line 1]: is_removal=false, word_sim=0.667, char_sim=0.792
trace:         Replace (1-to-1): preserving context line: '#include <linux/mroute.h>'
trace:         1-to-1 replacement line validation [line 2]: is_removal=false, word_sim=0.667, char_sim=0.720
trace:         Replace (1-to-1): preserving context line: '#include <linux/mroute6.h>'
trace:       DiffOp::Equal: 2 line(s) aligned (hunk old_idx=3, file new_idx=3)
trace:         Equal: removing target line: '#include <linux/scc.h>'
trace:         Equal: preserving target line: '#include <linux/serial.h>'
trace:       DiffOp::Replace: hunk lines 5..7 (len=2) vs file lines 5..7 (len=2)
trace:         1-to-1 length replacement. Validating similarity of modified lines...
trace:         1-to-1 replacement line validation [line 5]: is_removal=false, word_sim=0.667, char_sim=0.636
trace:         Replace (1-to-1): preserving context line: '#include <sys/msg.h>'
trace:         1-to-1 replacement line validation [line 6]: is_removal=false, word_sim=0.667, char_sim=0.636
trace:         Replace (1-to-1): preserving context line: '#include <sys/ipc.h>'
debug:     Robust reconstruction complete: produced 6 replacement line(s) for 7 target line(s).
trace:   Splicing final replacement block into target lines: range [155..162], replacement line count=6
  try_apply_hunk_at_location: successfully spliced hunk at line 156 (replaced 7 line(s), resulting target lines=1270)
trace:     Replaced lines: ["#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>", "#include <linux/scc.h>", "#include <linux/serial.h>", "#include <sys/msg.h>", "#include <sys/ipc.h>"]
debug:   Candidate 5/16 at HunkLocation { start_index: 155, length: 7 } succeeded! Hunk applied cleanly.
debug:   HunkApplier: hunk 1 application outcome: Applied { location: HunkLocation { start_index: 155, length: 7 }, match_type: Fuzzy { score: 0.7496894389390946 }, replaced_lines: ["#include <linux/lp.h>", "#include <linux/mroute.h>", "#include <linux/mroute6.h>", "#include <linux/scc.h>", "#include <linux/serial.h>", "#include <sys/msg.h>", "#include <sys/ipc.h>"] }
trace:   HunkApplier: hunk 1 applied at line 156 (len=7), delta=-1, target lines now=1270
  Applying Hunk 1/2...
debug:     Successfully applied Hunk 1 at line 156 via Fuzzy { score: 0.7496894389390946 }
trace:     Replaced lines:
trace:       - #include <linux/lp.h>
trace:       - #include <linux/mroute.h>
trace:       - #include <linux/mroute6.h>
trace:       - #include <linux/scc.h>
trace:       - #include <linux/serial.h>
trace:       - #include <sys/msg.h>
trace:       - #include <sys/ipc.h>
trace:   HunkApplier: shifting hunk 2 line hint from 400 to 399 (cumulative delta=-1)
debug: apply_hunk_to_lines: applying hunk with 7 line(s) against target with 1270 line(s)
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:   Match block: ["  unsigned struct_input_id_sz = sizeof(struct input_id);", "  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_scc_sz = sizeof(struct scc);", "  unsigned struct_termio_sz = sizeof(struct termio);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);", "  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);"]
trace: Hunk::get_replace_block: extracted 6 replacement line(s)
trace:   Replace block: ["  unsigned struct_input_id_sz = sizeof(struct input_id);", "  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_termio_sz = sizeof(struct termio);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);", "  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);"]
trace: Hunk::has_changes: true
trace: Hunk::get_match_block: extracted 7 match line(s)
trace: Hunk::required_match_span: calculated required match span as 1 line(s) (first_match_idx=Some(3), last_match_idx=Some(3))
trace: DefaultHunkFinder::find_candidate_locations: match block len=7, required_match_span=1, target lines=1270
trace:   find_hunk_location_internal: match_block has 7 lines (entropy=true), target has 1270 lines
trace:   find_hunk_location_internal called for a hunk with 7 lines to match against 1270 target lines.
trace:     Attempting exact match for hunk (match block has 7 line(s))...
trace: tie_break_with_line_number: strategy='exact', hint=Some(399), entropy=true
trace:       No exact matches found.
trace:     Strategy 1 (Exact): no exact match found.
trace:     Attempting exact match (ignoring trailing whitespace) for hunk (match block has 7 line(s))...
trace: tie_break_with_line_number: strategy='exact (ignoring whitespace)', hint=Some(399), entropy=true
trace:       No exact (ignoring whitespace) matches found.
trace:     Strategy 2 (Whitespace-insensitive): no match found.
debug:     Strategy 3 (Fuzzy): beginning flexible window fuzzy search (threshold=0.70, match block len=0.7)
trace:       Hunk match block (7 lines): ["  unsigned struct_input_id_sz = sizeof(struct input_id);", "  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_scc_sz = sizeof(struct scc);", "  unsigned struct_termio_sz = sizeof(struct termio);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);", "  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);"]
trace:       Searching with window sizes from 2 to 30 (hunk size: 7, fuzz distance: 23)
debug:       find_search_ranges: analyzing 7 match line(s) against 1270 target line(s).
trace:         Identified 7 high-entropy candidate anchor line(s) (search_radius=15, max candidates to test=100)
debug:         Spatial consensus: 5 anchor(s) agree on start near line 413
debug:       Found anchor line (hunk line 6) with 1 occurrences.
trace:         Anchor text: 'unsigned struct_vt_consize_sz = sizeof(struct vt_consize);'
trace:         Occurrence at target line 420: window estimated [400..459] (search radius +/-15)
trace:         Raw ranges before merging: [(399, 459)]
trace: merge_ranges: merging 1 input range(s): [(399, 459)]
trace: merge_ranges: result 1 disjoint range(s): [(399, 459)]
debug:       Search ranges merged: 1 disjoint range(s) covering 60/1270 line(s) (95.3% pruned): [(399, 459)]
trace:     Using search ranges: [(399, 459)]
debug:       compute_scored_windows (parallel): evaluating 1305 candidate window(s) across 1 range(s) (window lengths 2..=30)
trace:         Match block length: 7, Target line count: 1270, Search ranges: [(399, 459)]
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.474
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.671
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.424
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.473
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.638
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.516
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.484
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.621
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.448
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.585
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.492
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.528
trace:         score_window: window_len=20, match_len=7, line_score=0.389, ratio_lines=0.222, final_score=0.389
trace:         score_window: window_len=21, match_len=7, line_score=0.514, ratio_lines=0.286, final_score=0.514
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.495
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.538
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.503
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.591
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.475
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.509
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.643
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.459
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.552
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.497
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.544
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.604
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.516
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.541
trace:         score_window: window_len=19, match_len=7, line_score=0.392, ratio_lines=0.231, final_score=0.392
trace:         score_window: window_len=20, match_len=7, line_score=0.518, ratio_lines=0.296, final_score=0.518
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.484
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.509
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.459
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.552
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.560
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.516
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.547
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.534
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.523
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.509
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.493
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.597
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.552
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.549
trace:         score_window: window_len=18, match_len=7, line_score=0.395, ratio_lines=0.240, final_score=0.395
trace:         score_window: window_len=19, match_len=7, line_score=0.522, ratio_lines=0.308, final_score=0.522
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.576
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.555
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.555
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.560
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.533
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.517
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.538
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.523
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.470
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.407
trace:         score_window: window_len=17, match_len=7, line_score=0.398, ratio_lines=0.250, final_score=0.398
trace:         score_window: window_len=18, match_len=7, line_score=0.527, ratio_lines=0.320, final_score=0.527
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.607
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.582
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.582
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.560
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.558
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.517
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.579
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.523
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.612
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.407
trace:         score_window: window_len=16, match_len=7, line_score=0.401, ratio_lines=0.261, final_score=0.401
trace:         score_window: window_len=17, match_len=7, line_score=0.531, ratio_lines=0.333, final_score=0.531
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.543
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.587
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.474
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.560
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.587
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.517
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.563
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.541
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.488
trace:         score_window: window_len=15, match_len=7, line_score=0.404, ratio_lines=0.273, final_score=0.404
trace:         score_window: window_len=16, match_len=7, line_score=0.535, ratio_lines=0.348, final_score=0.535
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.584
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.537
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.561
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.560
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.517
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.537
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.482
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.484
trace:         score_window: window_len=14, match_len=7, line_score=0.407, ratio_lines=0.286, final_score=0.407
trace:         score_window: window_len=15, match_len=7, line_score=0.539, ratio_lines=0.364, final_score=0.539
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.514
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.560
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.517
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.540
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.523
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.407
trace:         score_window: window_len=12, match_len=7, line_score=0.276, ratio_lines=0.211, final_score=0.276
trace:         score_window: window_len=13, match_len=7, line_score=0.410, ratio_lines=0.300, final_score=0.410
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.488
trace:         score_window: window_len=14, match_len=7, line_score=0.543, ratio_lines=0.381, final_score=0.543
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.481
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.484
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.560
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.494
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.517
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.523
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.485
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.407
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.407
trace:         score_window: window_len=11, match_len=7, line_score=0.278, ratio_lines=0.222, final_score=0.278
trace:         score_window: window_len=12, match_len=7, line_score=0.413, ratio_lines=0.316, final_score=0.413
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.496
trace:         score_window: window_len=13, match_len=7, line_score=0.547, ratio_lines=0.400, final_score=0.547
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.472
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.504
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.530
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.534
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.530
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.500
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.557
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.560
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.517
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.485
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.474
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.523
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.433
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.442
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.494
trace:         score_window: window_len=10, match_len=7, line_score=0.280, ratio_lines=0.235, final_score=0.280
trace:         score_window: window_len=11, match_len=7, line_score=0.416, ratio_lines=0.333, final_score=0.416
trace:         score_window: window_len=12, match_len=7, line_score=0.551, ratio_lines=0.421, final_score=0.551
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.428
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.431
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.431
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.455
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.450
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.367
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.393
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.560
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.366
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.517
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.384
trace:         score_window: window_len=8, match_len=7, line_score=0.142, ratio_lines=0.133, final_score=0.142
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.384
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.413
trace:         score_window: window_len=9, match_len=7, line_score=0.282, ratio_lines=0.250, final_score=0.282
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.413
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.407
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.305
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.285
trace:         score_window: window_len=10, match_len=7, line_score=0.419, ratio_lines=0.353, final_score=0.419
trace:         score_window: window_len=11, match_len=7, line_score=0.555, ratio_lines=0.444, final_score=0.555
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.329
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.329
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.364
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.364
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.354
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.260
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.262
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.267
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.274
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.303
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.309
trace:         score_window: window_len=7, match_len=7, line_score=0.143, ratio_lines=0.143, final_score=0.143
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.297
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.517
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.350
trace:         score_window: window_len=8, match_len=7, line_score=0.284, ratio_lines=0.267, final_score=0.284
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.396
trace:         score_window: window_len=9, match_len=7, line_score=0.422, ratio_lines=0.375, final_score=0.422
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.287
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.407
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.280
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.325
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.331
trace:         score_window: window_len=10, match_len=7, line_score=0.559, ratio_lines=0.471, final_score=0.559
trace:         score_window: window_len=11, match_len=7, line_score=0.694, ratio_lines=0.556, final_score=0.694
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.317
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.371
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.419
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.327
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.290
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.333
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.282
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.319
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.374
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.422
trace:         score_window: window_len=7, match_len=7, line_score=0.286, ratio_lines=0.286, final_score=0.286
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.356
trace:         score_window: window_len=6, match_len=7, line_score=0.154, ratio_lines=0.154, final_score=0.154
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.356
trace:         score_window: window_len=8, match_len=7, line_score=0.426, ratio_lines=0.400, final_score=0.426
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.345
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.311
trace:         score_window: window_len=9, match_len=7, line_score=0.563, ratio_lines=0.500, final_score=0.563
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.311
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.407
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.448
trace:         score_window: window_len=10, match_len=7, line_score=0.699, ratio_lines=0.588, final_score=0.699
trace:         score_window: window_len=11, match_len=7, line_score=0.694, ratio_lines=0.556, final_score=0.694
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.490
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.280
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.345
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.448
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.490
trace:         score_window: window_len=7, match_len=7, line_score=0.429, ratio_lines=0.429, final_score=0.429
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.273
trace:         score_window: window_len=6, match_len=7, line_score=0.308, ratio_lines=0.308, final_score=0.308
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.361
trace:         score_window: window_len=8, match_len=7, line_score=0.567, ratio_lines=0.533, final_score=0.567
trace:         score_window: window_len=5, match_len=7, line_score=0.167, ratio_lines=0.167, final_score=0.167
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.407
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.443
trace:         score_window: window_len=10, match_len=7, line_score=0.699, ratio_lines=0.588, final_score=0.699
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.504
trace:         score_window: window_len=11, match_len=7, line_score=0.694, ratio_lines=0.556, final_score=0.694
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.487
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.375
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.300
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.459
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.520
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.516
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=7, match_len=7, line_score=0.571, ratio_lines=0.571, final_score=0.571
trace:         score_window: window_len=6, match_len=7, line_score=0.462, ratio_lines=0.462, final_score=0.462
trace:         score_window: window_len=5, match_len=7, line_score=0.333, ratio_lines=0.333, final_score=0.333
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.484
trace:         score_window: window_len=4, match_len=7, line_score=0.182, ratio_lines=0.182, final_score=0.182
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.507
trace:         score_window: window_len=10, match_len=7, line_score=0.699, ratio_lines=0.588, final_score=0.699
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.417
trace:         score_window: window_len=11, match_len=7, line_score=0.694, ratio_lines=0.556, final_score=0.694
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.571
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.537
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.510
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.481
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.576
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.512
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.541
trace:         score_window: window_len=6, match_len=7, line_score=0.615, ratio_lines=0.615, final_score=0.615
trace:         score_window: window_len=5, match_len=7, line_score=0.500, ratio_lines=0.500, final_score=0.500
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.523
trace:         score_window: window_len=4, match_len=7, line_score=0.364, ratio_lines=0.364, final_score=0.364
trace:         score_window: window_len=10, match_len=7, line_score=0.699, ratio_lines=0.588, final_score=0.699
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.490
trace:         score_window: window_len=11, match_len=7, line_score=0.694, ratio_lines=0.556, final_score=0.694
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.567
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.607
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.546
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.541
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.510
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.560
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.572
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.523
trace:         score_window: window_len=5, match_len=7, line_score=0.667, ratio_lines=0.667, final_score=0.667
trace:         score_window: window_len=4, match_len=7, line_score=0.545, ratio_lines=0.545, final_score=0.545
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.613
trace:         score_window: window_len=10, match_len=7, line_score=0.699, ratio_lines=0.588, final_score=0.699
trace:         score_window: window_len=3, match_len=7, line_score=0.400, ratio_lines=0.400, final_score=0.400
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.547
trace:         score_window: window_len=11, match_len=7, line_score=0.694, ratio_lines=0.556, final_score=0.694
trace:         score_window: window_len=2, match_len=7, line_score=0.222, ratio_lines=0.222, final_score=0.222
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.560
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.517
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.513
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.517
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=5, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.547
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=4, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.407
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=7, match_len=7, line_score=0.143, ratio_lines=0.143, final_score=0.179
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=8, match_len=7, line_score=0.142, ratio_lines=0.133, final_score=0.168
trace:         score_window: window_len=10, match_len=7, line_score=0.699, ratio_lines=0.588, final_score=0.699
trace:         score_window: window_len=3, match_len=7, line_score=0.600, ratio_lines=0.600, final_score=0.600
trace:         score_window: window_len=11, match_len=7, line_score=0.694, ratio_lines=0.556, final_score=0.694
trace:         score_window: window_len=2, match_len=7, line_score=0.444, ratio_lines=0.444, final_score=0.444
trace:         score_window: window_len=12, match_len=7, line_score=0.689, ratio_lines=0.526, final_score=0.689
trace:         score_window: window_len=9, match_len=7, line_score=0.141, ratio_lines=0.125, final_score=0.160
trace:         score_window: window_len=10, match_len=7, line_score=0.140, ratio_lines=0.118, final_score=0.158
trace:         score_window: window_len=13, match_len=7, line_score=0.684, ratio_lines=0.500, final_score=0.684
trace:         score_window: window_len=14, match_len=7, line_score=0.679, ratio_lines=0.476, final_score=0.679
trace:         score_window: window_len=11, match_len=7, line_score=0.139, ratio_lines=0.111, final_score=0.145
trace:         score_window: window_len=2, match_len=7, line_score=0.222, ratio_lines=0.222, final_score=0.222
trace:         score_window: window_len=12, match_len=7, line_score=0.138, ratio_lines=0.105, final_score=0.138
trace:         score_window: window_len=15, match_len=7, line_score=0.673, ratio_lines=0.455, final_score=0.673
trace:         score_window: window_len=16, match_len=7, line_score=0.668, ratio_lines=0.435, final_score=0.668
trace:         score_window: window_len=13, match_len=7, line_score=0.137, ratio_lines=0.100, final_score=0.137
trace:         score_window: window_len=17, match_len=7, line_score=0.663, ratio_lines=0.417, final_score=0.663
trace:         score_window: window_len=18, match_len=7, line_score=0.658, ratio_lines=0.400, final_score=0.658
trace:         score_window: window_len=19, match_len=7, line_score=0.653, ratio_lines=0.385, final_score=0.653
trace:         score_window: window_len=20, match_len=7, line_score=0.648, ratio_lines=0.370, final_score=0.648
trace:         score_window: window_len=14, match_len=7, line_score=0.136, ratio_lines=0.095, final_score=0.136
trace:         score_window: window_len=21, match_len=7, line_score=0.643, ratio_lines=0.357, final_score=0.643
trace:         score_window: window_len=22, match_len=7, line_score=0.638, ratio_lines=0.345, final_score=0.638
trace:         score_window: window_len=23, match_len=7, line_score=0.633, ratio_lines=0.333, final_score=0.633
trace:         score_window: window_len=24, match_len=7, line_score=0.628, ratio_lines=0.323, final_score=0.628
trace:         score_window: window_len=25, match_len=7, line_score=0.622, ratio_lines=0.312, final_score=0.622
trace:         score_window: window_len=26, match_len=7, line_score=0.617, ratio_lines=0.303, final_score=0.617
trace:         score_window: window_len=27, match_len=7, line_score=0.612, ratio_lines=0.294, final_score=0.612
trace:         score_window: window_len=15, match_len=7, line_score=0.135, ratio_lines=0.091, final_score=0.135
trace:         score_window: window_len=28, match_len=7, line_score=0.607, ratio_lines=0.286, final_score=0.607
trace:         score_window: window_len=29, match_len=7, line_score=0.602, ratio_lines=0.278, final_score=0.602
trace:         score_window: window_len=30, match_len=7, line_score=0.597, ratio_lines=0.270, final_score=0.597
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.289
trace:         score_window: window_len=7, match_len=7, line_score=0.571, ratio_lines=0.571, final_score=0.646
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.289
trace:         score_window: window_len=6, match_len=7, line_score=0.615, ratio_lines=0.615, final_score=0.651
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.162
trace:         score_window: window_len=8, match_len=7, line_score=0.567, ratio_lines=0.533, final_score=0.608
trace:         score_window: window_len=5, match_len=7, line_score=0.667, ratio_lines=0.667, final_score=0.679
trace:         score_window: window_len=9, match_len=7, line_score=0.563, ratio_lines=0.500, final_score=0.583
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.227
trace:         score_window: window_len=10, match_len=7, line_score=0.559, ratio_lines=0.471, final_score=0.559
trace:         score_window: window_len=3, match_len=7, line_score=0.600, ratio_lines=0.600, final_score=0.600
trace:         score_window: window_len=11, match_len=7, line_score=0.555, ratio_lines=0.444, final_score=0.555
trace:         score_window: window_len=2, match_len=7, line_score=0.444, ratio_lines=0.444, final_score=0.444
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.284
trace:         score_window: window_len=12, match_len=7, line_score=0.551, ratio_lines=0.421, final_score=0.551
trace:         score_window: window_len=13, match_len=7, line_score=0.547, ratio_lines=0.400, final_score=0.547
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.284
trace:         score_window: window_len=14, match_len=7, line_score=0.543, ratio_lines=0.381, final_score=0.543
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.329
trace:         score_window: window_len=15, match_len=7, line_score=0.539, ratio_lines=0.364, final_score=0.539
trace:         score_window: window_len=16, match_len=7, line_score=0.535, ratio_lines=0.348, final_score=0.535
trace:         score_window: window_len=17, match_len=7, line_score=0.531, ratio_lines=0.333, final_score=0.531
trace:         score_window: window_len=18, match_len=7, line_score=0.527, ratio_lines=0.320, final_score=0.527
trace:         score_window: window_len=15, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.373
trace:         score_window: window_len=19, match_len=7, line_score=0.522, ratio_lines=0.308, final_score=0.522
trace:         score_window: window_len=20, match_len=7, line_score=0.518, ratio_lines=0.296, final_score=0.518
trace:         score_window: window_len=21, match_len=7, line_score=0.514, ratio_lines=0.286, final_score=0.514
trace:         score_window: window_len=22, match_len=7, line_score=0.510, ratio_lines=0.276, final_score=0.510
trace:         score_window: window_len=23, match_len=7, line_score=0.506, ratio_lines=0.267, final_score=0.506
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.144
trace:         score_window: window_len=24, match_len=7, line_score=0.502, ratio_lines=0.258, final_score=0.502
trace:         score_window: window_len=25, match_len=7, line_score=0.498, ratio_lines=0.250, final_score=0.498
trace:         score_window: window_len=26, match_len=7, line_score=0.494, ratio_lines=0.242, final_score=0.494
trace:         score_window: window_len=27, match_len=7, line_score=0.490, ratio_lines=0.235, final_score=0.490
trace:         score_window: window_len=28, match_len=7, line_score=0.486, ratio_lines=0.229, final_score=0.486
trace:         score_window: window_len=29, match_len=7, line_score=0.482, ratio_lines=0.222, final_score=0.482
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.240
trace:         score_window: window_len=30, match_len=7, line_score=0.478, ratio_lines=0.216, final_score=0.478
trace:         score_window: window_len=7, match_len=7, line_score=0.429, ratio_lines=0.429, final_score=0.505
trace:         score_window: window_len=6, match_len=7, line_score=0.462, ratio_lines=0.462, final_score=0.539
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.312
trace:         score_window: window_len=8, match_len=7, line_score=0.426, ratio_lines=0.400, final_score=0.483
trace:         score_window: window_len=5, match_len=7, line_score=0.500, ratio_lines=0.500, final_score=0.543
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.317
trace:         score_window: window_len=9, match_len=7, line_score=0.422, ratio_lines=0.375, final_score=0.458
trace:         score_window: window_len=4, match_len=7, line_score=0.545, ratio_lines=0.545, final_score=0.569
trace:         score_window: window_len=10, match_len=7, line_score=0.419, ratio_lines=0.353, final_score=0.435
trace:         score_window: window_len=3, match_len=7, line_score=0.600, ratio_lines=0.600, final_score=0.600
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.382
trace:         score_window: window_len=11, match_len=7, line_score=0.416, ratio_lines=0.333, final_score=0.417
trace:         score_window: window_len=2, match_len=7, line_score=0.444, ratio_lines=0.444, final_score=0.444
trace:         score_window: window_len=12, match_len=7, line_score=0.413, ratio_lines=0.316, final_score=0.413
trace:         score_window: window_len=13, match_len=7, line_score=0.410, ratio_lines=0.300, final_score=0.410
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.325
trace:         score_window: window_len=14, match_len=7, line_score=0.407, ratio_lines=0.286, final_score=0.407
trace:         score_window: window_len=15, match_len=7, line_score=0.404, ratio_lines=0.273, final_score=0.404
trace:         score_window: window_len=15, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.370
trace:         score_window: window_len=16, match_len=7, line_score=0.401, ratio_lines=0.261, final_score=0.401
trace:         score_window: window_len=17, match_len=7, line_score=0.398, ratio_lines=0.250, final_score=0.398
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.150
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.249
trace:         score_window: window_len=18, match_len=7, line_score=0.395, ratio_lines=0.240, final_score=0.395
trace:         score_window: window_len=19, match_len=7, line_score=0.392, ratio_lines=0.231, final_score=0.392
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.323
trace:         score_window: window_len=20, match_len=7, line_score=0.389, ratio_lines=0.222, final_score=0.389
trace:         score_window: window_len=21, match_len=7, line_score=0.386, ratio_lines=0.214, final_score=0.386
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.328
trace:         score_window: window_len=7, match_len=7, line_score=0.286, ratio_lines=0.286, final_score=0.357
trace:         score_window: window_len=6, match_len=7, line_score=0.308, ratio_lines=0.308, final_score=0.375
trace:         score_window: window_len=8, match_len=7, line_score=0.284, ratio_lines=0.267, final_score=0.338
trace:         score_window: window_len=5, match_len=7, line_score=0.333, ratio_lines=0.333, final_score=0.362
trace:         score_window: window_len=9, match_len=7, line_score=0.282, ratio_lines=0.250, final_score=0.319
trace:         score_window: window_len=4, match_len=7, line_score=0.364, ratio_lines=0.364, final_score=0.373
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.394
trace:         score_window: window_len=10, match_len=7, line_score=0.280, ratio_lines=0.235, final_score=0.305
trace:         score_window: window_len=3, match_len=7, line_score=0.400, ratio_lines=0.400, final_score=0.400
trace:         score_window: window_len=11, match_len=7, line_score=0.278, ratio_lines=0.222, final_score=0.301
trace:         score_window: window_len=2, match_len=7, line_score=0.444, ratio_lines=0.444, final_score=0.444
trace:         score_window: window_len=12, match_len=7, line_score=0.276, ratio_lines=0.211, final_score=0.279
trace:         score_window: window_len=13, match_len=7, line_score=0.273, ratio_lines=0.200, final_score=0.273
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.335
trace:         score_window: window_len=14, match_len=7, line_score=0.271, ratio_lines=0.190, final_score=0.271
trace:         score_window: window_len=15, match_len=7, line_score=0.269, ratio_lines=0.182, final_score=0.269
trace:         score_window: window_len=14, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.380
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.150
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.249
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.356
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.278
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.323
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.328
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.362
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.394
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.432
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.337
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.378
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.383
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.265
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.425
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.342
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.347
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.467
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.415
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.355
trace:         score_window: window_len=7, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.382
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.401
trace:         score_window: window_len=6, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.376
trace:         score_window: window_len=13, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.443
trace:         score_window: window_len=8, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.454
trace:         score_window: window_len=9, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.400
trace:         score_window: window_len=10, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.448
trace:         score_window: window_len=11, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.490
trace:         score_window: window_len=12, match_len=7, line_score=0.000, ratio_lines=0.000, final_score=0.461
debug:       compute_scored_windows (parallel) complete: scored 1305 window(s). Best candidate score=0.833 at line 417 (len=5).
trace:       Top fuzzy match candidates:
trace:         - Index 416, Len 5: Score 0.833 (Ratio 0.833) | Content: ["  unsigned struct_input_id_sz = sizeof(struct input_id);", "  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);", "  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);"]
trace:         - Index 415, Len 6: Score 0.769 (Ratio 0.769) | Content: ["  unsigned struct_input_absinfo_sz = sizeof(struct input_absinfo);", "  unsigned struct_input_id_sz = sizeof(struct input_id);", "  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);", "  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);"]
trace:         - Index 416, Len 6: Score 0.769 (Ratio 0.769) | Content: ["  unsigned struct_input_id_sz = sizeof(struct input_id);", "  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);", "  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);", "  unsigned struct_vt_stat_sz = sizeof(struct vt_stat);"]
trace:         - Index 416, Len 4: Score 0.727 (Ratio 0.727) | Content: ["  unsigned struct_input_id_sz = sizeof(struct input_id);", "  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);"]
trace:         - Index 417, Len 4: Score 0.727 (Ratio 0.727) | Content: ["  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);", "  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);"]
trace:         New best score: 0.671 (ratio 0.671 [l:0.000,w:0.800]) at index 399 (window len 7)
trace:         New best score: 0.676 (ratio 0.676 [l:0.000,w:0.000]) at index 399 (window len 9)
trace:         New best score: 0.698 (ratio 0.698 [l:0.000,w:0.000]) at index 404 (window len 8)
trace:         New best score: 0.699 (ratio 0.699 [l:0.588,w:0.588]) at index 411 (window len 10)
trace:         New best score: 0.704 (ratio 0.704 [l:0.625,w:0.704]) at index 412 (window len 9)
trace:         New best score: 0.709 (ratio 0.709 [l:0.667,w:0.709]) at index 413 (window len 8)
trace:         New best score: 0.714 (ratio 0.714 [l:0.714,w:0.714]) at index 414 (window len 7)
trace:         Tie in score (0.714) and ratio (0.714). Adding candidate: index 415, len 7
trace:         New best score: 0.769 (ratio 0.769 [l:0.769,w:0.769]) at index 415 (window len 6)
trace:         Tie in score (0.769) and ratio (0.769). Adding candidate: index 416, len 6
trace:         New best score: 0.833 (ratio 0.833 [l:0.833,w:0.833]) at index 416 (window len 5)
debug:     Strategy 3 (Fuzzy): 17 window(s) met threshold 0.70
trace:       Top 3 passing candidates: [("0.833", 417, 5), ("0.769", 416, 6), ("0.769", 417, 6)]
debug:     Top fuzzy candidate: start line 417 (len=5, score=0.833)
trace:       Adding candidate location at line 416 (len=6, score=0.769)
trace:       Adding candidate location at line 417 (len=6, score=0.769)
trace:       Adding candidate location at line 417 (len=4, score=0.727)
trace:       Adding candidate location at line 418 (len=4, score=0.727)
trace:       Adding candidate location at line 415 (len=7, score=0.714)
trace:       Adding candidate location at line 416 (len=7, score=0.714)
trace:       Adding candidate location at line 417 (len=7, score=0.714)
trace:       Adding candidate location at line 414 (len=8, score=0.709)
trace:       Adding candidate location at line 415 (len=8, score=0.709)
trace:       Adding candidate location at line 416 (len=8, score=0.709)
trace:       Adding candidate location at line 417 (len=8, score=0.709)
trace:       Adding candidate location at line 413 (len=9, score=0.704)
trace:       Adding candidate location at line 414 (len=9, score=0.704)
trace:       Adding candidate location at line 415 (len=9, score=0.704)
trace:       Adding candidate location at line 416 (len=9, score=0.704)
debug:     Strategy 3 (Fuzzy): selected 16 candidate location(s)
trace:   Pruned candidates by min_span 1: 16 -> 16 candidate(s)
trace: DefaultHunkFinder::find_candidate_locations: returning 16 candidate(s)
debug:   Found 16 candidate location(s) for hunk. Testing sequentially...
trace:   Evaluating candidate 1/16 at location HunkLocation { start_index: 416, length: 5 } (match_type: Fuzzy { score: 0.8333333134651184 })
debug:   Found location HunkLocation { start_index: 416, length: 5 } with match type Fuzzy { score: 0.8333333134651184 }. Applying changes.
debug:   try_apply_hunk_at_location: target line 417 (length 5), match_type=Fuzzy { score: 0.8333333134651184 }, total target lines=1270.
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:     Match block lines: 7 | Total hunk lines: 7
trace:     Target slice to replace: ["  unsigned struct_input_id_sz = sizeof(struct input_id);", "  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);", "  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);"]
trace:     Ellipsis flags: has_ellipsis=false, is_literal_match=false, is_wildcard_gap_match=false
debug:     Applying hunk via robust reconstruction logic (preserving file context & adjusting indent).
trace:       Fuzzy match location: start=416, len=5
trace:       File content in matched range (5 line(s)): ["  unsigned struct_input_id_sz = sizeof(struct input_id);", "  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);", "  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);"]
trace:       Parsed hunk: 7 match line(s), 0 initial addition(s).
trace: Hunk::get_match_block: extracted 7 match line(s)
trace:       Computed diff between match block and file slice: 3 operation(s), similarity ratio=0.833
trace:       Initial Indentation Context: Hunk='  ', Target='  '
trace:       Active baseline indentation: hunk='  ', target='  '
trace:       DiffOp::Equal: 3 line(s) aligned (hunk old_idx=0, file new_idx=0)
trace:         Equal: preserving target line: '  unsigned struct_input_id_sz = sizeof(struct input_id);'
trace:         Equal: preserving target line: '  unsigned struct_mtpos_sz = sizeof(struct mtpos);'
trace:         Equal: preserving target line: '  unsigned struct_rtentry_sz = sizeof(struct rtentry);'
trace:       DiffOp::Delete: 2 line(s) missing from target file (hunk old_idx=3)
trace:         Skipping deleted line "  unsigned struct_scc_sz = sizeof(struct scc);" from old hunk, applying its 0 addition(s)
trace:         Skipping stale context line missing in target: "  unsigned struct_termio_sz = sizeof(struct termio);"
trace:       DiffOp::Equal: 2 line(s) aligned (hunk old_idx=5, file new_idx=3)
trace:         Equal: preserving target line: '  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);'
trace:         Equal: preserving target line: '  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);'
debug:     Robust reconstruction complete: produced 5 replacement line(s) for 5 target line(s).
trace:   Splicing final replacement block into target lines: range [416..421], replacement line count=5
  try_apply_hunk_at_location: successfully spliced hunk at line 417 (replaced 5 line(s), resulting target lines=1270)
trace:     Replaced lines: ["  unsigned struct_input_id_sz = sizeof(struct input_id);", "  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);", "  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);"]
debug:   Candidate 1/16 at HunkLocation { start_index: 416, length: 5 } succeeded! Hunk applied cleanly.
debug:   HunkApplier: hunk 2 application outcome: Applied { location: HunkLocation { start_index: 416, length: 5 }, match_type: Fuzzy { score: 0.8333333134651184 }, replaced_lines: ["  unsigned struct_input_id_sz = sizeof(struct input_id);", "  unsigned struct_mtpos_sz = sizeof(struct mtpos);", "  unsigned struct_rtentry_sz = sizeof(struct rtentry);", "  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);", "  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);"] }
trace:   HunkApplier: hunk 2 applied at line 417 (len=5), delta=0, target lines now=1270
  Applying Hunk 2/2...
debug:     Successfully applied Hunk 2 at line 417 via Fuzzy { score: 0.8333333134651184 }
trace:     Replaced lines:
trace:       -   unsigned struct_input_id_sz = sizeof(struct input_id);
trace:       -   unsigned struct_mtpos_sz = sizeof(struct mtpos);
trace:       -   unsigned struct_rtentry_sz = sizeof(struct rtentry);
trace:       -   unsigned struct_vt_consize_sz = sizeof(struct vt_consize);
trace:       -   unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);
debug: HunkApplier::into_content: assembling final content from 1270 line(s) (touched_eof=false, patch_ends_with_newline=true, original_ends_with_newline=true)
trace: HunkApplier::into_content: resulting content has 49603 bytes (1270 lines, ends_with_newline=true)
trace:   Ensuring parent directory exists: '<TARGET_DIR>/libsanitizer/sanitizer_common'
trace:   Writing 49603 bytes to '<TARGET_DIR>/libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc'
  Successfully wrote changes to 'libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc'
debug: apply_patches_to_dir: completed 1 patch(es). all_succeeded=true, all_applied_cleanly=true

>>> Operation 1/1

--- Summary ---
Successful operations: 1
Failed operations:     0
````

## Final Target File(s)

> This section shows the state of the target files *after* the patch operation was attempted.

### File: `libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc`

````cc
//===-- sanitizer_platform_limits_posix.cc --------------------------------===//
//
// This file is distributed under the University of Illinois Open Source
// License. See LICENSE.TXT for details.
//
//===----------------------------------------------------------------------===//
//
// This file is a part of Sanitizer common code.
//
// Sizes and layouts of platform-specific POSIX data structures.
//===----------------------------------------------------------------------===//

#include "sanitizer_platform.h"

#if SANITIZER_LINUX || SANITIZER_FREEBSD || SANITIZER_MAC
// Tests in this file assume that off_t-dependent data structures match the
// libc ABI. For example, struct dirent here is what readdir() function (as
// exported from libc) returns, and not the user-facing "dirent", which
// depends on _FILE_OFFSET_BITS setting.
// To get this "true" dirent definition, we undefine _FILE_OFFSET_BITS below.
#ifdef _FILE_OFFSET_BITS
#undef _FILE_OFFSET_BITS
#endif
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <grp.h>
#include <limits.h>
#include <net/if.h>
#include <netdb.h>
#include <poll.h>
#include <pthread.h>
#include <pwd.h>
#include <signal.h>
#include <stddef.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/times.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <termios.h>
#include <time.h>
#include <wchar.h>

#if !SANITIZER_IOS
#include <net/route.h>
#endif

#if !SANITIZER_ANDROID
#include <sys/mount.h>
#include <sys/timeb.h>
#endif

#if SANITIZER_LINUX
#include <malloc.h>
#include <mntent.h>
#include <netinet/ether.h>
#include <sys/sysinfo.h>
#include <sys/vt.h>
#include <linux/cdrom.h>
#include <linux/fd.h>
#include <linux/fs.h>
#include <linux/hdreg.h>
#include <linux/input.h>
#include <linux/ioctl.h>
#include <linux/soundcard.h>
#include <linux/sysctl.h>
#include <linux/utsname.h>
#include <linux/posix_types.h>
#include <net/if_arp.h>
#endif

#if SANITIZER_FREEBSD
# include <sys/mount.h>
# include <sys/sockio.h>
# include <sys/socket.h>
# include <sys/filio.h>
# include <sys/signal.h>
# include <sys/timespec.h>
# include <sys/timex.h>
# include <sys/mqueue.h>
# include <sys/msg.h>
# include <sys/ipc.h>
# include <sys/msg.h>
# include <sys/statvfs.h>
# include <sys/soundcard.h>
# include <sys/mtio.h>
# include <sys/consio.h>
# include <sys/kbio.h>
# include <sys/link_elf.h>
# include <netinet/ip_mroute.h>
# include <netinet/in.h>
# include <net/ethernet.h>
# include <net/ppp_defs.h>
# include <glob.h>
# include <term.h>

#define _KERNEL  // to declare 'shminfo' structure
# include <sys/shm.h>
#undef _KERNEL

#undef INLINE  // to avoid clashes with sanitizers' definitions
#endif

#if SANITIZER_FREEBSD || SANITIZER_IOS
#undef IOC_DIRMASK
#endif

#if SANITIZER_LINUX || SANITIZER_FREEBSD
# include <utime.h>
# include <sys/ptrace.h>
# if defined(__mips64) || defined(__aarch64__) || defined(__arm__)
#  include <asm/ptrace.h>
#  ifdef __arm__
typedef struct user_fpregs elf_fpregset_t;
#  endif
# endif
# include <semaphore.h>
#endif

#if !SANITIZER_ANDROID
#include <ifaddrs.h>
#include <sys/ucontext.h>
#include <wordexp.h>
#endif

#if SANITIZER_LINUX && !SANITIZER_ANDROID
#include <glob.h>
#include <obstack.h>
#include <mqueue.h>
#include <net/if_ppp.h>
#include <netax25/ax25.h>
#include <netipx/ipx.h>
#include <netrom/netrom.h>
#if HAVE_RPC_XDR_H
# include <rpc/xdr.h>
#elif HAVE_TIRPC_RPC_XDR_H
# include <tirpc/rpc/xdr.h>
#endif
#include <scsi/scsi.h>
#include <sys/mtio.h>
#include <sys/kd.h>
#include <sys/shm.h>
#include <sys/statvfs.h>
#include <sys/timex.h>
#if defined(__mips64)
# include <sys/procfs.h>
#endif
#include <sys/user.h>
#include <linux/cyclades.h>
#include <linux/if_eql.h>
#include <linux/if_plip.h>
#include <linux/lp.h>
#include <linux/mroute.h>
#include <linux/mroute6.h>
#include <linux/serial.h>
#include <sys/msg.h>
#include <sys/ipc.h>
#endif // SANITIZER_LINUX && !SANITIZER_ANDROID

#if SANITIZER_ANDROID
#include <linux/kd.h>
#include <linux/mtio.h>
#include <linux/ppp_defs.h>
#include <linux/if_ppp.h>
#endif

#if SANITIZER_LINUX
#include <link.h>
#include <sys/vfs.h>
#include <sys/epoll.h>
#include <linux/capability.h>
#endif // SANITIZER_LINUX

#if SANITIZER_MAC
#include <net/ethernet.h>
#include <sys/filio.h>
#include <sys/sockio.h>
#endif

// Include these after system headers to avoid name clashes and ambiguities.
#include "sanitizer_internal_defs.h"
#include "sanitizer_platform_limits_posix.h"

namespace __sanitizer {
  unsigned struct_utsname_sz = sizeof(struct utsname);
  unsigned struct_stat_sz = sizeof(struct stat);
#if !SANITIZER_IOS && !SANITIZER_FREEBSD
  unsigned struct_stat64_sz = sizeof(struct stat64);
#endif // !SANITIZER_IOS && !SANITIZER_FREEBSD
  unsigned struct_rusage_sz = sizeof(struct rusage);
  unsigned struct_tm_sz = sizeof(struct tm);
  unsigned struct_passwd_sz = sizeof(struct passwd);
  unsigned struct_group_sz = sizeof(struct group);
  unsigned siginfo_t_sz = sizeof(siginfo_t);
  unsigned struct_sigaction_sz = sizeof(struct sigaction);
  unsigned struct_itimerval_sz = sizeof(struct itimerval);
  unsigned pthread_t_sz = sizeof(pthread_t);
  unsigned pthread_cond_t_sz = sizeof(pthread_cond_t);
  unsigned pid_t_sz = sizeof(pid_t);
  unsigned timeval_sz = sizeof(timeval);
  unsigned uid_t_sz = sizeof(uid_t);
  unsigned gid_t_sz = sizeof(gid_t);
  unsigned mbstate_t_sz = sizeof(mbstate_t);
  unsigned sigset_t_sz = sizeof(sigset_t);
  unsigned struct_timezone_sz = sizeof(struct timezone);
  unsigned struct_tms_sz = sizeof(struct tms);
  unsigned struct_sigevent_sz = sizeof(struct sigevent);
  unsigned struct_sched_param_sz = sizeof(struct sched_param);


#if SANITIZER_MAC && !SANITIZER_IOS
  unsigned struct_statfs64_sz = sizeof(struct statfs64);
#endif // SANITIZER_MAC && !SANITIZER_IOS

#if !SANITIZER_ANDROID
  unsigned struct_statfs_sz = sizeof(struct statfs);
  unsigned struct_sockaddr_sz = sizeof(struct sockaddr);
  unsigned ucontext_t_sz = sizeof(ucontext_t);
#endif // !SANITIZER_ANDROID

#if SANITIZER_LINUX
  unsigned struct_epoll_event_sz = sizeof(struct epoll_event);
  unsigned struct_sysinfo_sz = sizeof(struct sysinfo);
  unsigned __user_cap_header_struct_sz =
      sizeof(struct __user_cap_header_struct);
  unsigned __user_cap_data_struct_sz = sizeof(struct __user_cap_data_struct);
  unsigned struct_new_utsname_sz = sizeof(struct new_utsname);
  unsigned struct_old_utsname_sz = sizeof(struct old_utsname);
  unsigned struct_oldold_utsname_sz = sizeof(struct oldold_utsname);
#endif // SANITIZER_LINUX

#if SANITIZER_LINUX || SANITIZER_FREEBSD
  unsigned struct_rlimit_sz = sizeof(struct rlimit);
  unsigned struct_timespec_sz = sizeof(struct timespec);
  unsigned struct_utimbuf_sz = sizeof(struct utimbuf);
  unsigned struct_itimerspec_sz = sizeof(struct itimerspec);
#endif // SANITIZER_LINUX || SANITIZER_FREEBSD

#if SANITIZER_LINUX && !SANITIZER_ANDROID
  // Use pre-computed size of struct ustat to avoid <sys/ustat.h> which
  // has been removed from glibc 2.28.
#if defined(__aarch64__) || defined(__s390x__) || defined (__mips64) \
  || defined(__powerpc64__) || defined(__arch64__) || defined(__sparcv9) \
  || defined(__x86_64__)
#define SIZEOF_STRUCT_USTAT 32
#elif defined(__arm__) || defined(__i386__) || defined(__mips__) \
  || defined(__powerpc__) || defined(__s390__) || defined(__sparc__)
#define SIZEOF_STRUCT_USTAT 20
#else
#error Unknown size of struct ustat
#endif
  unsigned struct_ustat_sz = SIZEOF_STRUCT_USTAT;
  unsigned struct_rlimit64_sz = sizeof(struct rlimit64);
  unsigned struct_statvfs64_sz = sizeof(struct statvfs64);
#endif // SANITIZER_LINUX && !SANITIZER_ANDROID

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
  unsigned struct_timex_sz = sizeof(struct timex);
  unsigned struct_msqid_ds_sz = sizeof(struct msqid_ds);
  unsigned struct_mq_attr_sz = sizeof(struct mq_attr);
  unsigned struct_statvfs_sz = sizeof(struct statvfs);
#endif // (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID

  uptr sig_ign = (uptr)SIG_IGN;
  uptr sig_dfl = (uptr)SIG_DFL;
  uptr sa_siginfo = (uptr)SA_SIGINFO;

#if SANITIZER_LINUX
  int e_tabsz = (int)E_TABSZ;
#endif


#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
  unsigned struct_shminfo_sz = sizeof(struct shminfo);
  unsigned struct_shm_info_sz = sizeof(struct shm_info);
  int shmctl_ipc_stat = (int)IPC_STAT;
  int shmctl_ipc_info = (int)IPC_INFO;
  int shmctl_shm_info = (int)SHM_INFO;
  int shmctl_shm_stat = (int)SHM_STAT;
#endif

  int map_fixed = MAP_FIXED;

  int af_inet = (int)AF_INET;
  int af_inet6 = (int)AF_INET6;

  uptr __sanitizer_in_addr_sz(int af) {
    if (af == AF_INET)
      return sizeof(struct in_addr);
    else if (af == AF_INET6)
      return sizeof(struct in6_addr);
    else
      return 0;
  }

#if SANITIZER_LINUX
unsigned struct_ElfW_Phdr_sz = sizeof(ElfW(Phdr));
#elif SANITIZER_FREEBSD
unsigned struct_ElfW_Phdr_sz = sizeof(Elf_Phdr);
#endif

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
  int glob_nomatch = GLOB_NOMATCH;
  int glob_altdirfunc = GLOB_ALTDIRFUNC;
#endif

#if SANITIZER_LINUX && !SANITIZER_ANDROID && \
    (defined(__i386) || defined(__x86_64) || defined(__mips64) || \
      defined(__powerpc64__) || defined(__aarch64__) || defined(__arm__))
#if defined(__mips64) || defined(__powerpc64__) || defined(__arm__)
  unsigned struct_user_regs_struct_sz = sizeof(struct pt_regs);
  unsigned struct_user_fpregs_struct_sz = sizeof(elf_fpregset_t);
#elif defined(__aarch64__)
  unsigned struct_user_regs_struct_sz = sizeof(struct user_pt_regs);
  unsigned struct_user_fpregs_struct_sz = sizeof(struct user_fpsimd_state);
#else
  unsigned struct_user_regs_struct_sz = sizeof(struct user_regs_struct);
  unsigned struct_user_fpregs_struct_sz = sizeof(struct user_fpregs_struct);
#endif // __mips64 || __powerpc64__ || __aarch64__
#if defined(__x86_64) || defined(__mips64) || defined(__powerpc64__) || \
    defined(__aarch64__) || defined(__arm__)
  unsigned struct_user_fpxregs_struct_sz = 0;
#else
  unsigned struct_user_fpxregs_struct_sz = sizeof(struct user_fpxregs_struct);
#endif // __x86_64 || __mips64 || __powerpc64__ || __aarch64__ || __arm__
#ifdef __arm__
  unsigned struct_user_vfpregs_struct_sz = ARM_VFPREGS_SIZE;
#else
  unsigned struct_user_vfpregs_struct_sz = 0;
#endif

  int ptrace_peektext = PTRACE_PEEKTEXT;
  int ptrace_peekdata = PTRACE_PEEKDATA;
  int ptrace_peekuser = PTRACE_PEEKUSER;
#if (defined(PTRACE_GETREGS) && defined(PTRACE_SETREGS)) || \
    (defined(PT_GETREGS) && defined(PT_SETREGS))
  int ptrace_getregs = PTRACE_GETREGS;
  int ptrace_setregs = PTRACE_SETREGS;
#else
  int ptrace_getregs = -1;
  int ptrace_setregs = -1;
#endif
#if (defined(PTRACE_GETFPREGS) && defined(PTRACE_SETFPREGS)) || \
    (defined(PT_GETFPREGS) && defined(PT_SETFPREGS))
  int ptrace_getfpregs = PTRACE_GETFPREGS;
  int ptrace_setfpregs = PTRACE_SETFPREGS;
#else
  int ptrace_getfpregs = -1;
  int ptrace_setfpregs = -1;
#endif
#if (defined(PTRACE_GETFPXREGS) && defined(PTRACE_SETFPXREGS)) || \
    (defined(PT_GETFPXREGS) && defined(PT_SETFPXREGS))
  int ptrace_getfpxregs = PTRACE_GETFPXREGS;
  int ptrace_setfpxregs = PTRACE_SETFPXREGS;
#else
  int ptrace_getfpxregs = -1;
  int ptrace_setfpxregs = -1;
#endif // PTRACE_GETFPXREGS/PTRACE_SETFPXREGS
#if defined(PTRACE_GETVFPREGS) && defined(PTRACE_SETVFPREGS)
  int ptrace_getvfpregs = PTRACE_GETVFPREGS;
  int ptrace_setvfpregs = PTRACE_SETVFPREGS;
#else
  int ptrace_getvfpregs = -1;
  int ptrace_setvfpregs = -1;
#endif
  int ptrace_geteventmsg = PTRACE_GETEVENTMSG;
#if (defined(PTRACE_GETSIGINFO) && defined(PTRACE_SETSIGINFO)) ||              \
    (defined(PT_GETSIGINFO) && defined(PT_SETSIGINFO))
  int ptrace_getsiginfo = PTRACE_GETSIGINFO;
  int ptrace_setsiginfo = PTRACE_SETSIGINFO;
#else
  int ptrace_getsiginfo = -1;
  int ptrace_setsiginfo = -1;
#endif // PTRACE_GETSIGINFO/PTRACE_SETSIGINFO
#if defined(PTRACE_GETREGSET) && defined(PTRACE_SETREGSET)
  int ptrace_getregset = PTRACE_GETREGSET;
  int ptrace_setregset = PTRACE_SETREGSET;
#else
  int ptrace_getregset = -1;
  int ptrace_setregset = -1;
#endif // PTRACE_GETREGSET/PTRACE_SETREGSET
#endif

  unsigned path_max = PATH_MAX;

  // ioctl arguments
  unsigned struct_ifreq_sz = sizeof(struct ifreq);
  unsigned struct_termios_sz = sizeof(struct termios);
  unsigned struct_winsize_sz = sizeof(struct winsize);

#if SANITIZER_LINUX
  unsigned struct_arpreq_sz = sizeof(struct arpreq);
  unsigned struct_cdrom_msf_sz = sizeof(struct cdrom_msf);
  unsigned struct_cdrom_multisession_sz = sizeof(struct cdrom_multisession);
  unsigned struct_cdrom_read_audio_sz = sizeof(struct cdrom_read_audio);
  unsigned struct_cdrom_subchnl_sz = sizeof(struct cdrom_subchnl);
  unsigned struct_cdrom_ti_sz = sizeof(struct cdrom_ti);
  unsigned struct_cdrom_tocentry_sz = sizeof(struct cdrom_tocentry);
  unsigned struct_cdrom_tochdr_sz = sizeof(struct cdrom_tochdr);
  unsigned struct_cdrom_volctrl_sz = sizeof(struct cdrom_volctrl);
  unsigned struct_ff_effect_sz = sizeof(struct ff_effect);
  unsigned struct_floppy_drive_params_sz = sizeof(struct floppy_drive_params);
  unsigned struct_floppy_drive_struct_sz = sizeof(struct floppy_drive_struct);
  unsigned struct_floppy_fdc_state_sz = sizeof(struct floppy_fdc_state);
  unsigned struct_floppy_max_errors_sz = sizeof(struct floppy_max_errors);
  unsigned struct_floppy_raw_cmd_sz = sizeof(struct floppy_raw_cmd);
  unsigned struct_floppy_struct_sz = sizeof(struct floppy_struct);
  unsigned struct_floppy_write_errors_sz = sizeof(struct floppy_write_errors);
  unsigned struct_format_descr_sz = sizeof(struct format_descr);
  unsigned struct_hd_driveid_sz = sizeof(struct hd_driveid);
  unsigned struct_hd_geometry_sz = sizeof(struct hd_geometry);
  unsigned struct_input_absinfo_sz = sizeof(struct input_absinfo);
  unsigned struct_input_id_sz = sizeof(struct input_id);
  unsigned struct_mtpos_sz = sizeof(struct mtpos);
  unsigned struct_rtentry_sz = sizeof(struct rtentry);
  unsigned struct_vt_consize_sz = sizeof(struct vt_consize);
  unsigned struct_vt_sizes_sz = sizeof(struct vt_sizes);
  unsigned struct_vt_stat_sz = sizeof(struct vt_stat);
#endif // SANITIZER_LINUX

#if SANITIZER_LINUX || SANITIZER_FREEBSD
#if SOUND_VERSION >= 0x040000
  unsigned struct_copr_buffer_sz = 0;
  unsigned struct_copr_debug_buf_sz = 0;
  unsigned struct_copr_msg_sz = 0;
#else
  unsigned struct_copr_buffer_sz = sizeof(struct copr_buffer);
  unsigned struct_copr_debug_buf_sz = sizeof(struct copr_debug_buf);
  unsigned struct_copr_msg_sz = sizeof(struct copr_msg);
#endif
  unsigned struct_midi_info_sz = sizeof(struct midi_info);
  unsigned struct_mtget_sz = sizeof(struct mtget);
  unsigned struct_mtop_sz = sizeof(struct mtop);
  unsigned struct_sbi_instrument_sz = sizeof(struct sbi_instrument);
  unsigned struct_seq_event_rec_sz = sizeof(struct seq_event_rec);
  unsigned struct_synth_info_sz = sizeof(struct synth_info);
  unsigned struct_vt_mode_sz = sizeof(struct vt_mode);
#endif // SANITIZER_LINUX || SANITIZER_FREEBSD

#if SANITIZER_LINUX && !SANITIZER_ANDROID
  unsigned struct_ax25_parms_struct_sz = sizeof(struct ax25_parms_struct);
  unsigned struct_cyclades_monitor_sz = sizeof(struct cyclades_monitor);
#if EV_VERSION > (0x010000)
  unsigned struct_input_keymap_entry_sz = sizeof(struct input_keymap_entry);
#else
  unsigned struct_input_keymap_entry_sz = 0;
#endif
  unsigned struct_ipx_config_data_sz = sizeof(struct ipx_config_data);
  unsigned struct_kbdiacrs_sz = sizeof(struct kbdiacrs);
  unsigned struct_kbentry_sz = sizeof(struct kbentry);
  unsigned struct_kbkeycode_sz = sizeof(struct kbkeycode);
  unsigned struct_kbsentry_sz = sizeof(struct kbsentry);
  unsigned struct_mtconfiginfo_sz = sizeof(struct mtconfiginfo);
  unsigned struct_nr_parms_struct_sz = sizeof(struct nr_parms_struct);
  unsigned struct_scc_modem_sz = sizeof(struct scc_modem);
  unsigned struct_scc_stat_sz = sizeof(struct scc_stat);
  unsigned struct_serial_multiport_struct_sz
      = sizeof(struct serial_multiport_struct);
  unsigned struct_serial_struct_sz = sizeof(struct serial_struct);
  unsigned struct_sockaddr_ax25_sz = sizeof(struct sockaddr_ax25);
  unsigned struct_unimapdesc_sz = sizeof(struct unimapdesc);
  unsigned struct_unimapinit_sz = sizeof(struct unimapinit);
#endif // SANITIZER_LINUX && !SANITIZER_ANDROID

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
  unsigned struct_audio_buf_info_sz = sizeof(struct audio_buf_info);
  unsigned struct_ppp_stats_sz = sizeof(struct ppp_stats);
#endif // (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID

#if !SANITIZER_ANDROID && !SANITIZER_MAC
  unsigned struct_sioc_sg_req_sz = sizeof(struct sioc_sg_req);
  unsigned struct_sioc_vif_req_sz = sizeof(struct sioc_vif_req);
#endif

  const unsigned IOCTL_NOT_PRESENT = 0;

  unsigned IOCTL_FIOASYNC = FIOASYNC;
  unsigned IOCTL_FIOCLEX = FIOCLEX;
  unsigned IOCTL_FIOGETOWN = FIOGETOWN;
  unsigned IOCTL_FIONBIO = FIONBIO;
  unsigned IOCTL_FIONCLEX = FIONCLEX;
  unsigned IOCTL_FIOSETOWN = FIOSETOWN;
  unsigned IOCTL_SIOCADDMULTI = SIOCADDMULTI;
  unsigned IOCTL_SIOCATMARK = SIOCATMARK;
  unsigned IOCTL_SIOCDELMULTI = SIOCDELMULTI;
  unsigned IOCTL_SIOCGIFADDR = SIOCGIFADDR;
  unsigned IOCTL_SIOCGIFBRDADDR = SIOCGIFBRDADDR;
  unsigned IOCTL_SIOCGIFCONF = SIOCGIFCONF;
  unsigned IOCTL_SIOCGIFDSTADDR = SIOCGIFDSTADDR;
  unsigned IOCTL_SIOCGIFFLAGS = SIOCGIFFLAGS;
  unsigned IOCTL_SIOCGIFMETRIC = SIOCGIFMETRIC;
  unsigned IOCTL_SIOCGIFMTU = SIOCGIFMTU;
  unsigned IOCTL_SIOCGIFNETMASK = SIOCGIFNETMASK;
  unsigned IOCTL_SIOCGPGRP = SIOCGPGRP;
  unsigned IOCTL_SIOCSIFADDR = SIOCSIFADDR;
  unsigned IOCTL_SIOCSIFBRDADDR = SIOCSIFBRDADDR;
  unsigned IOCTL_SIOCSIFDSTADDR = SIOCSIFDSTADDR;
  unsigned IOCTL_SIOCSIFFLAGS = SIOCSIFFLAGS;
  unsigned IOCTL_SIOCSIFMETRIC = SIOCSIFMETRIC;
  unsigned IOCTL_SIOCSIFMTU = SIOCSIFMTU;
  unsigned IOCTL_SIOCSIFNETMASK = SIOCSIFNETMASK;
  unsigned IOCTL_SIOCSPGRP = SIOCSPGRP;
  unsigned IOCTL_TIOCCONS = TIOCCONS;
  unsigned IOCTL_TIOCEXCL = TIOCEXCL;
  unsigned IOCTL_TIOCGETD = TIOCGETD;
  unsigned IOCTL_TIOCGPGRP = TIOCGPGRP;
  unsigned IOCTL_TIOCGWINSZ = TIOCGWINSZ;
  unsigned IOCTL_TIOCMBIC = TIOCMBIC;
  unsigned IOCTL_TIOCMBIS = TIOCMBIS;
  unsigned IOCTL_TIOCMGET = TIOCMGET;
  unsigned IOCTL_TIOCMSET = TIOCMSET;
  unsigned IOCTL_TIOCNOTTY = TIOCNOTTY;
  unsigned IOCTL_TIOCNXCL = TIOCNXCL;
  unsigned IOCTL_TIOCOUTQ = TIOCOUTQ;
  unsigned IOCTL_TIOCPKT = TIOCPKT;
  unsigned IOCTL_TIOCSCTTY = TIOCSCTTY;
  unsigned IOCTL_TIOCSETD = TIOCSETD;
  unsigned IOCTL_TIOCSPGRP = TIOCSPGRP;
  unsigned IOCTL_TIOCSTI = TIOCSTI;
  unsigned IOCTL_TIOCSWINSZ = TIOCSWINSZ;
#if ((SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID)
  unsigned IOCTL_SIOCGETSGCNT = SIOCGETSGCNT;
  unsigned IOCTL_SIOCGETVIFCNT = SIOCGETVIFCNT;
#endif

#if SANITIZER_LINUX
  unsigned IOCTL_EVIOCGABS = EVIOCGABS(0);
  unsigned IOCTL_EVIOCGBIT = EVIOCGBIT(0, 0);
  unsigned IOCTL_EVIOCGEFFECTS = EVIOCGEFFECTS;
  unsigned IOCTL_EVIOCGID = EVIOCGID;
  unsigned IOCTL_EVIOCGKEY = EVIOCGKEY(0);
  unsigned IOCTL_EVIOCGKEYCODE = EVIOCGKEYCODE;
  unsigned IOCTL_EVIOCGLED = EVIOCGLED(0);
  unsigned IOCTL_EVIOCGNAME = EVIOCGNAME(0);
  unsigned IOCTL_EVIOCGPHYS = EVIOCGPHYS(0);
  unsigned IOCTL_EVIOCGRAB = EVIOCGRAB;
  unsigned IOCTL_EVIOCGREP = EVIOCGREP;
  unsigned IOCTL_EVIOCGSND = EVIOCGSND(0);
  unsigned IOCTL_EVIOCGSW = EVIOCGSW(0);
  unsigned IOCTL_EVIOCGUNIQ = EVIOCGUNIQ(0);
  unsigned IOCTL_EVIOCGVERSION = EVIOCGVERSION;
  unsigned IOCTL_EVIOCRMFF = EVIOCRMFF;
  unsigned IOCTL_EVIOCSABS = EVIOCSABS(0);
  unsigned IOCTL_EVIOCSFF = EVIOCSFF;
  unsigned IOCTL_EVIOCSKEYCODE = EVIOCSKEYCODE;
  unsigned IOCTL_EVIOCSREP = EVIOCSREP;
  unsigned IOCTL_BLKFLSBUF = BLKFLSBUF;
  unsigned IOCTL_BLKGETSIZE = BLKGETSIZE;
  unsigned IOCTL_BLKRAGET = BLKRAGET;
  unsigned IOCTL_BLKRASET = BLKRASET;
  unsigned IOCTL_BLKROGET = BLKROGET;
  unsigned IOCTL_BLKROSET = BLKROSET;
  unsigned IOCTL_BLKRRPART = BLKRRPART;
  unsigned IOCTL_CDROMAUDIOBUFSIZ = CDROMAUDIOBUFSIZ;
  unsigned IOCTL_CDROMEJECT = CDROMEJECT;
  unsigned IOCTL_CDROMEJECT_SW = CDROMEJECT_SW;
  unsigned IOCTL_CDROMMULTISESSION = CDROMMULTISESSION;
  unsigned IOCTL_CDROMPAUSE = CDROMPAUSE;
  unsigned IOCTL_CDROMPLAYMSF = CDROMPLAYMSF;
  unsigned IOCTL_CDROMPLAYTRKIND = CDROMPLAYTRKIND;
  unsigned IOCTL_CDROMREADAUDIO = CDROMREADAUDIO;
  unsigned IOCTL_CDROMREADCOOKED = CDROMREADCOOKED;
  unsigned IOCTL_CDROMREADMODE1 = CDROMREADMODE1;
  unsigned IOCTL_CDROMREADMODE2 = CDROMREADMODE2;
  unsigned IOCTL_CDROMREADRAW = CDROMREADRAW;
  unsigned IOCTL_CDROMREADTOCENTRY = CDROMREADTOCENTRY;
  unsigned IOCTL_CDROMREADTOCHDR = CDROMREADTOCHDR;
  unsigned IOCTL_CDROMRESET = CDROMRESET;
  unsigned IOCTL_CDROMRESUME = CDROMRESUME;
  unsigned IOCTL_CDROMSEEK = CDROMSEEK;
  unsigned IOCTL_CDROMSTART = CDROMSTART;
  unsigned IOCTL_CDROMSTOP = CDROMSTOP;
  unsigned IOCTL_CDROMSUBCHNL = CDROMSUBCHNL;
  unsigned IOCTL_CDROMVOLCTRL = CDROMVOLCTRL;
  unsigned IOCTL_CDROMVOLREAD = CDROMVOLREAD;
  unsigned IOCTL_CDROM_GET_UPC = CDROM_GET_UPC;
  unsigned IOCTL_FDCLRPRM = FDCLRPRM;
  unsigned IOCTL_FDDEFPRM = FDDEFPRM;
  unsigned IOCTL_FDFLUSH = FDFLUSH;
  unsigned IOCTL_FDFMTBEG = FDFMTBEG;
  unsigned IOCTL_FDFMTEND = FDFMTEND;
  unsigned IOCTL_FDFMTTRK = FDFMTTRK;
  unsigned IOCTL_FDGETDRVPRM = FDGETDRVPRM;
  unsigned IOCTL_FDGETDRVSTAT = FDGETDRVSTAT;
  unsigned IOCTL_FDGETDRVTYP = FDGETDRVTYP;
  unsigned IOCTL_FDGETFDCSTAT = FDGETFDCSTAT;
  unsigned IOCTL_FDGETMAXERRS = FDGETMAXERRS;
  unsigned IOCTL_FDGETPRM = FDGETPRM;
  unsigned IOCTL_FDMSGOFF = FDMSGOFF;
  unsigned IOCTL_FDMSGON = FDMSGON;
  unsigned IOCTL_FDPOLLDRVSTAT = FDPOLLDRVSTAT;
  unsigned IOCTL_FDRAWCMD = FDRAWCMD;
  unsigned IOCTL_FDRESET = FDRESET;
  unsigned IOCTL_FDSETDRVPRM = FDSETDRVPRM;
  unsigned IOCTL_FDSETEMSGTRESH = FDSETEMSGTRESH;
  unsigned IOCTL_FDSETMAXERRS = FDSETMAXERRS;
  unsigned IOCTL_FDSETPRM = FDSETPRM;
  unsigned IOCTL_FDTWADDLE = FDTWADDLE;
  unsigned IOCTL_FDWERRORCLR = FDWERRORCLR;
  unsigned IOCTL_FDWERRORGET = FDWERRORGET;
  unsigned IOCTL_HDIO_DRIVE_CMD = HDIO_DRIVE_CMD;
  unsigned IOCTL_HDIO_GETGEO = HDIO_GETGEO;
  unsigned IOCTL_HDIO_GET_32BIT = HDIO_GET_32BIT;
  unsigned IOCTL_HDIO_GET_DMA = HDIO_GET_DMA;
  unsigned IOCTL_HDIO_GET_IDENTITY = HDIO_GET_IDENTITY;
  unsigned IOCTL_HDIO_GET_KEEPSETTINGS = HDIO_GET_KEEPSETTINGS;
  unsigned IOCTL_HDIO_GET_MULTCOUNT = HDIO_GET_MULTCOUNT;
  unsigned IOCTL_HDIO_GET_NOWERR = HDIO_GET_NOWERR;
  unsigned IOCTL_HDIO_GET_UNMASKINTR = HDIO_GET_UNMASKINTR;
  unsigned IOCTL_HDIO_SET_32BIT = HDIO_SET_32BIT;
  unsigned IOCTL_HDIO_SET_DMA = HDIO_SET_DMA;
  unsigned IOCTL_HDIO_SET_KEEPSETTINGS = HDIO_SET_KEEPSETTINGS;
  unsigned IOCTL_HDIO_SET_MULTCOUNT = HDIO_SET_MULTCOUNT;
  unsigned IOCTL_HDIO_SET_NOWERR = HDIO_SET_NOWERR;
  unsigned IOCTL_HDIO_SET_UNMASKINTR = HDIO_SET_UNMASKINTR;
  unsigned IOCTL_MTIOCPOS = MTIOCPOS;
  unsigned IOCTL_PPPIOCGASYNCMAP = PPPIOCGASYNCMAP;
  unsigned IOCTL_PPPIOCGDEBUG = PPPIOCGDEBUG;
  unsigned IOCTL_PPPIOCGFLAGS = PPPIOCGFLAGS;
  unsigned IOCTL_PPPIOCGUNIT = PPPIOCGUNIT;
  unsigned IOCTL_PPPIOCGXASYNCMAP = PPPIOCGXASYNCMAP;
  unsigned IOCTL_PPPIOCSASYNCMAP = PPPIOCSASYNCMAP;
  unsigned IOCTL_PPPIOCSDEBUG = PPPIOCSDEBUG;
  unsigned IOCTL_PPPIOCSFLAGS = PPPIOCSFLAGS;
  unsigned IOCTL_PPPIOCSMAXCID = PPPIOCSMAXCID;
  unsigned IOCTL_PPPIOCSMRU = PPPIOCSMRU;
  unsigned IOCTL_PPPIOCSXASYNCMAP = PPPIOCSXASYNCMAP;
  unsigned IOCTL_SIOCADDRT = SIOCADDRT;
  unsigned IOCTL_SIOCDARP = SIOCDARP;
  unsigned IOCTL_SIOCDELRT = SIOCDELRT;
  unsigned IOCTL_SIOCDRARP = SIOCDRARP;
  unsigned IOCTL_SIOCGARP = SIOCGARP;
  unsigned IOCTL_SIOCGIFENCAP = SIOCGIFENCAP;
  unsigned IOCTL_SIOCGIFHWADDR = SIOCGIFHWADDR;
  unsigned IOCTL_SIOCGIFMAP = SIOCGIFMAP;
  unsigned IOCTL_SIOCGIFMEM = SIOCGIFMEM;
  unsigned IOCTL_SIOCGIFNAME = SIOCGIFNAME;
  unsigned IOCTL_SIOCGIFSLAVE = SIOCGIFSLAVE;
  unsigned IOCTL_SIOCGRARP = SIOCGRARP;
  unsigned IOCTL_SIOCGSTAMP = SIOCGSTAMP;
  unsigned IOCTL_SIOCSARP = SIOCSARP;
  unsigned IOCTL_SIOCSIFENCAP = SIOCSIFENCAP;
  unsigned IOCTL_SIOCSIFHWADDR = SIOCSIFHWADDR;
  unsigned IOCTL_SIOCSIFLINK = SIOCSIFLINK;
  unsigned IOCTL_SIOCSIFMAP = SIOCSIFMAP;
  unsigned IOCTL_SIOCSIFMEM = SIOCSIFMEM;
  unsigned IOCTL_SIOCSIFSLAVE = SIOCSIFSLAVE;
  unsigned IOCTL_SIOCSRARP = SIOCSRARP;
# if SOUND_VERSION >= 0x040000
  unsigned IOCTL_SNDCTL_COPR_HALT = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_LOAD = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_RCODE = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_RCVMSG = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_RDATA = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_RESET = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_RUN = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_SENDMSG = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_WCODE = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SNDCTL_COPR_WDATA = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_READ_BITS = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_READ_CHANNELS = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_READ_FILTER = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_READ_RATE = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_WRITE_CHANNELS = IOCTL_NOT_PRESENT;
  unsigned IOCTL_SOUND_PCM_WRITE_FILTER = IOCTL_NOT_PRESENT;
# else  // SOUND_VERSION
  unsigned IOCTL_SNDCTL_COPR_HALT = SNDCTL_COPR_HALT;
  unsigned IOCTL_SNDCTL_COPR_LOAD = SNDCTL_COPR_LOAD;
  unsigned IOCTL_SNDCTL_COPR_RCODE = SNDCTL_COPR_RCODE;
  unsigned IOCTL_SNDCTL_COPR_RCVMSG = SNDCTL_COPR_RCVMSG;
  unsigned IOCTL_SNDCTL_COPR_RDATA = SNDCTL_COPR_RDATA;
  unsigned IOCTL_SNDCTL_COPR_RESET = SNDCTL_COPR_RESET;
  unsigned IOCTL_SNDCTL_COPR_RUN = SNDCTL_COPR_RUN;
  unsigned IOCTL_SNDCTL_COPR_SENDMSG = SNDCTL_COPR_SENDMSG;
  unsigned IOCTL_SNDCTL_COPR_WCODE = SNDCTL_COPR_WCODE;
  unsigned IOCTL_SNDCTL_COPR_WDATA = SNDCTL_COPR_WDATA;
  unsigned IOCTL_SOUND_PCM_READ_BITS = SOUND_PCM_READ_BITS;
  unsigned IOCTL_SOUND_PCM_READ_CHANNELS = SOUND_PCM_READ_CHANNELS;
  unsigned IOCTL_SOUND_PCM_READ_FILTER = SOUND_PCM_READ_FILTER;
  unsigned IOCTL_SOUND_PCM_READ_RATE = SOUND_PCM_READ_RATE;
  unsigned IOCTL_SOUND_PCM_WRITE_CHANNELS = SOUND_PCM_WRITE_CHANNELS;
  unsigned IOCTL_SOUND_PCM_WRITE_FILTER = SOUND_PCM_WRITE_FILTER;
#endif // SOUND_VERSION
  unsigned IOCTL_TCFLSH = TCFLSH;
  unsigned IOCTL_TCGETA = TCGETA;
  unsigned IOCTL_TCGETS = TCGETS;
  unsigned IOCTL_TCSBRK = TCSBRK;
  unsigned IOCTL_TCSBRKP = TCSBRKP;
  unsigned IOCTL_TCSETA = TCSETA;
  unsigned IOCTL_TCSETAF = TCSETAF;
  unsigned IOCTL_TCSETAW = TCSETAW;
  unsigned IOCTL_TCSETS = TCSETS;
  unsigned IOCTL_TCSETSF = TCSETSF;
  unsigned IOCTL_TCSETSW = TCSETSW;
  unsigned IOCTL_TCXONC = TCXONC;
  unsigned IOCTL_TIOCGLCKTRMIOS = TIOCGLCKTRMIOS;
  unsigned IOCTL_TIOCGSOFTCAR = TIOCGSOFTCAR;
  unsigned IOCTL_TIOCINQ = TIOCINQ;
  unsigned IOCTL_TIOCLINUX = TIOCLINUX;
  unsigned IOCTL_TIOCSERCONFIG = TIOCSERCONFIG;
  unsigned IOCTL_TIOCSERGETLSR = TIOCSERGETLSR;
  unsigned IOCTL_TIOCSERGWILD = TIOCSERGWILD;
  unsigned IOCTL_TIOCSERSWILD = TIOCSERSWILD;
  unsigned IOCTL_TIOCSLCKTRMIOS = TIOCSLCKTRMIOS;
  unsigned IOCTL_TIOCSSOFTCAR = TIOCSSOFTCAR;
  unsigned IOCTL_VT_DISALLOCATE = VT_DISALLOCATE;
  unsigned IOCTL_VT_GETSTATE = VT_GETSTATE;
  unsigned IOCTL_VT_RESIZE = VT_RESIZE;
  unsigned IOCTL_VT_RESIZEX = VT_RESIZEX;
  unsigned IOCTL_VT_SENDSIG = VT_SENDSIG;
#endif // SANITIZER_LINUX

#if SANITIZER_LINUX || SANITIZER_FREEBSD
  unsigned IOCTL_MTIOCGET = MTIOCGET;
  unsigned IOCTL_MTIOCTOP = MTIOCTOP;
  unsigned IOCTL_SNDCTL_DSP_GETBLKSIZE = SNDCTL_DSP_GETBLKSIZE;
  unsigned IOCTL_SNDCTL_DSP_GETFMTS = SNDCTL_DSP_GETFMTS;
  unsigned IOCTL_SNDCTL_DSP_NONBLOCK = SNDCTL_DSP_NONBLOCK;
  unsigned IOCTL_SNDCTL_DSP_POST = SNDCTL_DSP_POST;
  unsigned IOCTL_SNDCTL_DSP_RESET = SNDCTL_DSP_RESET;
  unsigned IOCTL_SNDCTL_DSP_SETFMT = SNDCTL_DSP_SETFMT;
  unsigned IOCTL_SNDCTL_DSP_SETFRAGMENT = SNDCTL_DSP_SETFRAGMENT;
  unsigned IOCTL_SNDCTL_DSP_SPEED = SNDCTL_DSP_SPEED;
  unsigned IOCTL_SNDCTL_DSP_STEREO = SNDCTL_DSP_STEREO;
  unsigned IOCTL_SNDCTL_DSP_SUBDIVIDE = SNDCTL_DSP_SUBDIVIDE;
  unsigned IOCTL_SNDCTL_DSP_SYNC = SNDCTL_DSP_SYNC;
  unsigned IOCTL_SNDCTL_FM_4OP_ENABLE = SNDCTL_FM_4OP_ENABLE;
  unsigned IOCTL_SNDCTL_FM_LOAD_INSTR = SNDCTL_FM_LOAD_INSTR;
  unsigned IOCTL_SNDCTL_MIDI_INFO = SNDCTL_MIDI_INFO;
  unsigned IOCTL_SNDCTL_MIDI_PRETIME = SNDCTL_MIDI_PRETIME;
  unsigned IOCTL_SNDCTL_SEQ_CTRLRATE = SNDCTL_SEQ_CTRLRATE;
  unsigned IOCTL_SNDCTL_SEQ_GETINCOUNT = SNDCTL_SEQ_GETINCOUNT;
  unsigned IOCTL_SNDCTL_SEQ_GETOUTCOUNT = SNDCTL_SEQ_GETOUTCOUNT;
  unsigned IOCTL_SNDCTL_SEQ_NRMIDIS = SNDCTL_SEQ_NRMIDIS;
  unsigned IOCTL_SNDCTL_SEQ_NRSYNTHS = SNDCTL_SEQ_NRSYNTHS;
  unsigned IOCTL_SNDCTL_SEQ_OUTOFBAND = SNDCTL_SEQ_OUTOFBAND;
  unsigned IOCTL_SNDCTL_SEQ_PANIC = SNDCTL_SEQ_PANIC;
  unsigned IOCTL_SNDCTL_SEQ_PERCMODE = SNDCTL_SEQ_PERCMODE;
  unsigned IOCTL_SNDCTL_SEQ_RESET = SNDCTL_SEQ_RESET;
  unsigned IOCTL_SNDCTL_SEQ_RESETSAMPLES = SNDCTL_SEQ_RESETSAMPLES;
  unsigned IOCTL_SNDCTL_SEQ_SYNC = SNDCTL_SEQ_SYNC;
  unsigned IOCTL_SNDCTL_SEQ_TESTMIDI = SNDCTL_SEQ_TESTMIDI;
  unsigned IOCTL_SNDCTL_SEQ_THRESHOLD = SNDCTL_SEQ_THRESHOLD;
  unsigned IOCTL_SNDCTL_SYNTH_INFO = SNDCTL_SYNTH_INFO;
  unsigned IOCTL_SNDCTL_SYNTH_MEMAVL = SNDCTL_SYNTH_MEMAVL;
  unsigned IOCTL_SNDCTL_TMR_CONTINUE = SNDCTL_TMR_CONTINUE;
  unsigned IOCTL_SNDCTL_TMR_METRONOME = SNDCTL_TMR_METRONOME;
  unsigned IOCTL_SNDCTL_TMR_SELECT = SNDCTL_TMR_SELECT;
  unsigned IOCTL_SNDCTL_TMR_SOURCE = SNDCTL_TMR_SOURCE;
  unsigned IOCTL_SNDCTL_TMR_START = SNDCTL_TMR_START;
  unsigned IOCTL_SNDCTL_TMR_STOP = SNDCTL_TMR_STOP;
  unsigned IOCTL_SNDCTL_TMR_TEMPO = SNDCTL_TMR_TEMPO;
  unsigned IOCTL_SNDCTL_TMR_TIMEBASE = SNDCTL_TMR_TIMEBASE;
  unsigned IOCTL_SOUND_MIXER_READ_ALTPCM = SOUND_MIXER_READ_ALTPCM;
  unsigned IOCTL_SOUND_MIXER_READ_BASS = SOUND_MIXER_READ_BASS;
  unsigned IOCTL_SOUND_MIXER_READ_CAPS = SOUND_MIXER_READ_CAPS;
  unsigned IOCTL_SOUND_MIXER_READ_CD = SOUND_MIXER_READ_CD;
  unsigned IOCTL_SOUND_MIXER_READ_DEVMASK = SOUND_MIXER_READ_DEVMASK;
  unsigned IOCTL_SOUND_MIXER_READ_ENHANCE = SOUND_MIXER_READ_ENHANCE;
  unsigned IOCTL_SOUND_MIXER_READ_IGAIN = SOUND_MIXER_READ_IGAIN;
  unsigned IOCTL_SOUND_MIXER_READ_IMIX = SOUND_MIXER_READ_IMIX;
  unsigned IOCTL_SOUND_MIXER_READ_LINE = SOUND_MIXER_READ_LINE;
  unsigned IOCTL_SOUND_MIXER_READ_LINE1 = SOUND_MIXER_READ_LINE1;
  unsigned IOCTL_SOUND_MIXER_READ_LINE2 = SOUND_MIXER_READ_LINE2;
  unsigned IOCTL_SOUND_MIXER_READ_LINE3 = SOUND_MIXER_READ_LINE3;
  unsigned IOCTL_SOUND_MIXER_READ_LOUD = SOUND_MIXER_READ_LOUD;
  unsigned IOCTL_SOUND_MIXER_READ_MIC = SOUND_MIXER_READ_MIC;
  unsigned IOCTL_SOUND_MIXER_READ_MUTE = SOUND_MIXER_READ_MUTE;
  unsigned IOCTL_SOUND_MIXER_READ_OGAIN = SOUND_MIXER_READ_OGAIN;
  unsigned IOCTL_SOUND_MIXER_READ_PCM = SOUND_MIXER_READ_PCM;
  unsigned IOCTL_SOUND_MIXER_READ_RECLEV = SOUND_MIXER_READ_RECLEV;
  unsigned IOCTL_SOUND_MIXER_READ_RECMASK = SOUND_MIXER_READ_RECMASK;
  unsigned IOCTL_SOUND_MIXER_READ_RECSRC = SOUND_MIXER_READ_RECSRC;
  unsigned IOCTL_SOUND_MIXER_READ_SPEAKER = SOUND_MIXER_READ_SPEAKER;
  unsigned IOCTL_SOUND_MIXER_READ_STEREODEVS = SOUND_MIXER_READ_STEREODEVS;
  unsigned IOCTL_SOUND_MIXER_READ_SYNTH = SOUND_MIXER_READ_SYNTH;
  unsigned IOCTL_SOUND_MIXER_READ_TREBLE = SOUND_MIXER_READ_TREBLE;
  unsigned IOCTL_SOUND_MIXER_READ_VOLUME = SOUND_MIXER_READ_VOLUME;
  unsigned IOCTL_SOUND_MIXER_WRITE_ALTPCM = SOUND_MIXER_WRITE_ALTPCM;
  unsigned IOCTL_SOUND_MIXER_WRITE_BASS = SOUND_MIXER_WRITE_BASS;
  unsigned IOCTL_SOUND_MIXER_WRITE_CD = SOUND_MIXER_WRITE_CD;
  unsigned IOCTL_SOUND_MIXER_WRITE_ENHANCE = SOUND_MIXER_WRITE_ENHANCE;
  unsigned IOCTL_SOUND_MIXER_WRITE_IGAIN = SOUND_MIXER_WRITE_IGAIN;
  unsigned IOCTL_SOUND_MIXER_WRITE_IMIX = SOUND_MIXER_WRITE_IMIX;
  unsigned IOCTL_SOUND_MIXER_WRITE_LINE = SOUND_MIXER_WRITE_LINE;
  unsigned IOCTL_SOUND_MIXER_WRITE_LINE1 = SOUND_MIXER_WRITE_LINE1;
  unsigned IOCTL_SOUND_MIXER_WRITE_LINE2 = SOUND_MIXER_WRITE_LINE2;
  unsigned IOCTL_SOUND_MIXER_WRITE_LINE3 = SOUND_MIXER_WRITE_LINE3;
  unsigned IOCTL_SOUND_MIXER_WRITE_LOUD = SOUND_MIXER_WRITE_LOUD;
  unsigned IOCTL_SOUND_MIXER_WRITE_MIC = SOUND_MIXER_WRITE_MIC;
  unsigned IOCTL_SOUND_MIXER_WRITE_MUTE = SOUND_MIXER_WRITE_MUTE;
  unsigned IOCTL_SOUND_MIXER_WRITE_OGAIN = SOUND_MIXER_WRITE_OGAIN;
  unsigned IOCTL_SOUND_MIXER_WRITE_PCM = SOUND_MIXER_WRITE_PCM;
  unsigned IOCTL_SOUND_MIXER_WRITE_RECLEV = SOUND_MIXER_WRITE_RECLEV;
  unsigned IOCTL_SOUND_MIXER_WRITE_RECSRC = SOUND_MIXER_WRITE_RECSRC;
  unsigned IOCTL_SOUND_MIXER_WRITE_SPEAKER = SOUND_MIXER_WRITE_SPEAKER;
  unsigned IOCTL_SOUND_MIXER_WRITE_SYNTH = SOUND_MIXER_WRITE_SYNTH;
  unsigned IOCTL_SOUND_MIXER_WRITE_TREBLE = SOUND_MIXER_WRITE_TREBLE;
  unsigned IOCTL_SOUND_MIXER_WRITE_VOLUME = SOUND_MIXER_WRITE_VOLUME;
  unsigned IOCTL_VT_ACTIVATE = VT_ACTIVATE;
  unsigned IOCTL_VT_GETMODE = VT_GETMODE;
  unsigned IOCTL_VT_OPENQRY = VT_OPENQRY;
  unsigned IOCTL_VT_RELDISP = VT_RELDISP;
  unsigned IOCTL_VT_SETMODE = VT_SETMODE;
  unsigned IOCTL_VT_WAITACTIVE = VT_WAITACTIVE;
#endif // SANITIZER_LINUX || SANITIZER_FREEBSD

#if SANITIZER_LINUX && !SANITIZER_ANDROID
  unsigned IOCTL_CYGETDEFTHRESH = CYGETDEFTHRESH;
  unsigned IOCTL_CYGETDEFTIMEOUT = CYGETDEFTIMEOUT;
  unsigned IOCTL_CYGETMON = CYGETMON;
  unsigned IOCTL_CYGETTHRESH = CYGETTHRESH;
  unsigned IOCTL_CYGETTIMEOUT = CYGETTIMEOUT;
  unsigned IOCTL_CYSETDEFTHRESH = CYSETDEFTHRESH;
  unsigned IOCTL_CYSETDEFTIMEOUT = CYSETDEFTIMEOUT;
  unsigned IOCTL_CYSETTHRESH = CYSETTHRESH;
  unsigned IOCTL_CYSETTIMEOUT = CYSETTIMEOUT;
  unsigned IOCTL_EQL_EMANCIPATE = EQL_EMANCIPATE;
  unsigned IOCTL_EQL_ENSLAVE = EQL_ENSLAVE;
  unsigned IOCTL_EQL_GETMASTRCFG = EQL_GETMASTRCFG;
  unsigned IOCTL_EQL_GETSLAVECFG = EQL_GETSLAVECFG;
  unsigned IOCTL_EQL_SETMASTRCFG = EQL_SETMASTRCFG;
  unsigned IOCTL_EQL_SETSLAVECFG = EQL_SETSLAVECFG;
#if EV_VERSION > (0x010000)
  unsigned IOCTL_EVIOCGKEYCODE_V2 = EVIOCGKEYCODE_V2;
  unsigned IOCTL_EVIOCGPROP = EVIOCGPROP(0);
  unsigned IOCTL_EVIOCSKEYCODE_V2 = EVIOCSKEYCODE_V2;
#else
  unsigned IOCTL_EVIOCGKEYCODE_V2 = IOCTL_NOT_PRESENT;
  unsigned IOCTL_EVIOCGPROP = IOCTL_NOT_PRESENT;
  unsigned IOCTL_EVIOCSKEYCODE_V2 = IOCTL_NOT_PRESENT;
#endif
  unsigned IOCTL_FS_IOC_GETFLAGS = FS_IOC_GETFLAGS;
  unsigned IOCTL_FS_IOC_GETVERSION = FS_IOC_GETVERSION;
  unsigned IOCTL_FS_IOC_SETFLAGS = FS_IOC_SETFLAGS;
  unsigned IOCTL_FS_IOC_SETVERSION = FS_IOC_SETVERSION;
  unsigned IOCTL_GIO_CMAP = GIO_CMAP;
  unsigned IOCTL_GIO_FONT = GIO_FONT;
  unsigned IOCTL_GIO_UNIMAP = GIO_UNIMAP;
  unsigned IOCTL_GIO_UNISCRNMAP = GIO_UNISCRNMAP;
  unsigned IOCTL_KDADDIO = KDADDIO;
  unsigned IOCTL_KDDELIO = KDDELIO;
  unsigned IOCTL_KDGETKEYCODE = KDGETKEYCODE;
  unsigned IOCTL_KDGKBDIACR = KDGKBDIACR;
  unsigned IOCTL_KDGKBENT = KDGKBENT;
  unsigned IOCTL_KDGKBLED = KDGKBLED;
  unsigned IOCTL_KDGKBMETA = KDGKBMETA;
  unsigned IOCTL_KDGKBSENT = KDGKBSENT;
  unsigned IOCTL_KDMAPDISP = KDMAPDISP;
  unsigned IOCTL_KDSETKEYCODE = KDSETKEYCODE;
  unsigned IOCTL_KDSIGACCEPT = KDSIGACCEPT;
  unsigned IOCTL_KDSKBDIACR = KDSKBDIACR;
  unsigned IOCTL_KDSKBENT = KDSKBENT;
  unsigned IOCTL_KDSKBLED = KDSKBLED;
  unsigned IOCTL_KDSKBMETA = KDSKBMETA;
  unsigned IOCTL_KDSKBSENT = KDSKBSENT;
  unsigned IOCTL_KDUNMAPDISP = KDUNMAPDISP;
  unsigned IOCTL_LPABORT = LPABORT;
  unsigned IOCTL_LPABORTOPEN = LPABORTOPEN;
  unsigned IOCTL_LPCAREFUL = LPCAREFUL;
  unsigned IOCTL_LPCHAR = LPCHAR;
  unsigned IOCTL_LPGETIRQ = LPGETIRQ;
  unsigned IOCTL_LPGETSTATUS = LPGETSTATUS;
  unsigned IOCTL_LPRESET = LPRESET;
  unsigned IOCTL_LPSETIRQ = LPSETIRQ;
  unsigned IOCTL_LPTIME = LPTIME;
  unsigned IOCTL_LPWAIT = LPWAIT;
  unsigned IOCTL_MTIOCGETCONFIG = MTIOCGETCONFIG;
  unsigned IOCTL_MTIOCSETCONFIG = MTIOCSETCONFIG;
  unsigned IOCTL_PIO_CMAP = PIO_CMAP;
  unsigned IOCTL_PIO_FONT = PIO_FONT;
  unsigned IOCTL_PIO_UNIMAP = PIO_UNIMAP;
  unsigned IOCTL_PIO_UNIMAPCLR = PIO_UNIMAPCLR;
  unsigned IOCTL_PIO_UNISCRNMAP = PIO_UNISCRNMAP;
  unsigned IOCTL_SCSI_IOCTL_GET_IDLUN = SCSI_IOCTL_GET_IDLUN;
  unsigned IOCTL_SCSI_IOCTL_PROBE_HOST = SCSI_IOCTL_PROBE_HOST;
  unsigned IOCTL_SCSI_IOCTL_TAGGED_DISABLE = SCSI_IOCTL_TAGGED_DISABLE;
  unsigned IOCTL_SCSI_IOCTL_TAGGED_ENABLE = SCSI_IOCTL_TAGGED_ENABLE;
  unsigned IOCTL_SIOCAIPXITFCRT = SIOCAIPXITFCRT;
  unsigned IOCTL_SIOCAIPXPRISLT = SIOCAIPXPRISLT;
  unsigned IOCTL_SIOCAX25ADDUID = SIOCAX25ADDUID;
  unsigned IOCTL_SIOCAX25DELUID = SIOCAX25DELUID;
  unsigned IOCTL_SIOCAX25GETPARMS = SIOCAX25GETPARMS;
  unsigned IOCTL_SIOCAX25GETUID = SIOCAX25GETUID;
  unsigned IOCTL_SIOCAX25NOUID = SIOCAX25NOUID;
  unsigned IOCTL_SIOCAX25SETPARMS = SIOCAX25SETPARMS;
  unsigned IOCTL_SIOCDEVPLIP = SIOCDEVPLIP;
  unsigned IOCTL_SIOCIPXCFGDATA = SIOCIPXCFGDATA;
  unsigned IOCTL_SIOCNRDECOBS = SIOCNRDECOBS;
  unsigned IOCTL_SIOCNRGETPARMS = SIOCNRGETPARMS;
  unsigned IOCTL_SIOCNRRTCTL = SIOCNRRTCTL;
  unsigned IOCTL_SIOCNRSETPARMS = SIOCNRSETPARMS;
  unsigned IOCTL_TIOCGSERIAL = TIOCGSERIAL;
  unsigned IOCTL_TIOCSERGETMULTI = TIOCSERGETMULTI;
  unsigned IOCTL_TIOCSERSETMULTI = TIOCSERSETMULTI;
  unsigned IOCTL_TIOCSSERIAL = TIOCSSERIAL;
#endif // SANITIZER_LINUX && !SANITIZER_ANDROID

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
  unsigned IOCTL_GIO_SCRNMAP = GIO_SCRNMAP;
  unsigned IOCTL_KDDISABIO = KDDISABIO;
  unsigned IOCTL_KDENABIO = KDENABIO;
  unsigned IOCTL_KDGETLED = KDGETLED;
  unsigned IOCTL_KDGETMODE = KDGETMODE;
  unsigned IOCTL_KDGKBMODE = KDGKBMODE;
  unsigned IOCTL_KDGKBTYPE = KDGKBTYPE;
  unsigned IOCTL_KDMKTONE = KDMKTONE;
  unsigned IOCTL_KDSETLED = KDSETLED;
  unsigned IOCTL_KDSETMODE = KDSETMODE;
  unsigned IOCTL_KDSKBMODE = KDSKBMODE;
  unsigned IOCTL_KIOCSOUND = KIOCSOUND;
  unsigned IOCTL_PIO_SCRNMAP = PIO_SCRNMAP;
  unsigned IOCTL_SNDCTL_DSP_GETISPACE = SNDCTL_DSP_GETISPACE;
  unsigned IOCTL_SNDCTL_DSP_GETOSPACE = SNDCTL_DSP_GETOSPACE;
#endif // (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID

  const int errno_EINVAL = EINVAL;
// EOWNERDEAD is not present in some older platforms.
#if defined(EOWNERDEAD)
  const int errno_EOWNERDEAD = EOWNERDEAD;
#else
  const int errno_EOWNERDEAD = -1;
#endif

  const int si_SEGV_MAPERR = SEGV_MAPERR;
  const int si_SEGV_ACCERR = SEGV_ACCERR;
} // namespace __sanitizer

COMPILER_CHECK(sizeof(__sanitizer_pthread_attr_t) >= sizeof(pthread_attr_t));

COMPILER_CHECK(sizeof(socklen_t) == sizeof(unsigned));
CHECK_TYPE_SIZE(pthread_key_t);

#if SANITIZER_LINUX
// FIXME: We define those on Linux and Mac, but only check on Linux.
COMPILER_CHECK(IOC_NRBITS == _IOC_NRBITS);
COMPILER_CHECK(IOC_TYPEBITS == _IOC_TYPEBITS);
COMPILER_CHECK(IOC_SIZEBITS == _IOC_SIZEBITS);
COMPILER_CHECK(IOC_DIRBITS == _IOC_DIRBITS);
COMPILER_CHECK(IOC_NRMASK == _IOC_NRMASK);
COMPILER_CHECK(IOC_TYPEMASK == _IOC_TYPEMASK);
COMPILER_CHECK(IOC_SIZEMASK == _IOC_SIZEMASK);
COMPILER_CHECK(IOC_DIRMASK == _IOC_DIRMASK);
COMPILER_CHECK(IOC_NRSHIFT == _IOC_NRSHIFT);
COMPILER_CHECK(IOC_TYPESHIFT == _IOC_TYPESHIFT);
COMPILER_CHECK(IOC_SIZESHIFT == _IOC_SIZESHIFT);
COMPILER_CHECK(IOC_DIRSHIFT == _IOC_DIRSHIFT);
COMPILER_CHECK(IOC_NONE == _IOC_NONE);
COMPILER_CHECK(IOC_WRITE == _IOC_WRITE);
COMPILER_CHECK(IOC_READ == _IOC_READ);
COMPILER_CHECK(EVIOC_ABS_MAX == ABS_MAX);
COMPILER_CHECK(EVIOC_EV_MAX == EV_MAX);
COMPILER_CHECK(IOC_SIZE(0x12345678) == _IOC_SIZE(0x12345678));
COMPILER_CHECK(IOC_DIR(0x12345678) == _IOC_DIR(0x12345678));
COMPILER_CHECK(IOC_NR(0x12345678) == _IOC_NR(0x12345678));
COMPILER_CHECK(IOC_TYPE(0x12345678) == _IOC_TYPE(0x12345678));
#endif // SANITIZER_LINUX

#if SANITIZER_LINUX || SANITIZER_FREEBSD
// There are more undocumented fields in dl_phdr_info that we are not interested
// in.
COMPILER_CHECK(sizeof(__sanitizer_dl_phdr_info) <= sizeof(dl_phdr_info));
CHECK_SIZE_AND_OFFSET(dl_phdr_info, dlpi_addr);
CHECK_SIZE_AND_OFFSET(dl_phdr_info, dlpi_name);
CHECK_SIZE_AND_OFFSET(dl_phdr_info, dlpi_phdr);
CHECK_SIZE_AND_OFFSET(dl_phdr_info, dlpi_phnum);
#endif // SANITIZER_LINUX || SANITIZER_FREEBSD

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
CHECK_TYPE_SIZE(glob_t);
CHECK_SIZE_AND_OFFSET(glob_t, gl_pathc);
CHECK_SIZE_AND_OFFSET(glob_t, gl_pathv);
CHECK_SIZE_AND_OFFSET(glob_t, gl_offs);
CHECK_SIZE_AND_OFFSET(glob_t, gl_flags);
CHECK_SIZE_AND_OFFSET(glob_t, gl_closedir);
CHECK_SIZE_AND_OFFSET(glob_t, gl_readdir);
CHECK_SIZE_AND_OFFSET(glob_t, gl_opendir);
CHECK_SIZE_AND_OFFSET(glob_t, gl_lstat);
CHECK_SIZE_AND_OFFSET(glob_t, gl_stat);
#endif

CHECK_TYPE_SIZE(addrinfo);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_flags);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_family);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_socktype);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_protocol);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_protocol);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_addrlen);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_canonname);
CHECK_SIZE_AND_OFFSET(addrinfo, ai_addr);

CHECK_TYPE_SIZE(hostent);
CHECK_SIZE_AND_OFFSET(hostent, h_name);
CHECK_SIZE_AND_OFFSET(hostent, h_aliases);
CHECK_SIZE_AND_OFFSET(hostent, h_addrtype);
CHECK_SIZE_AND_OFFSET(hostent, h_length);
CHECK_SIZE_AND_OFFSET(hostent, h_addr_list);

CHECK_TYPE_SIZE(iovec);
CHECK_SIZE_AND_OFFSET(iovec, iov_base);
CHECK_SIZE_AND_OFFSET(iovec, iov_len);

CHECK_TYPE_SIZE(msghdr);
CHECK_SIZE_AND_OFFSET(msghdr, msg_name);
CHECK_SIZE_AND_OFFSET(msghdr, msg_namelen);
CHECK_SIZE_AND_OFFSET(msghdr, msg_iov);
CHECK_SIZE_AND_OFFSET(msghdr, msg_iovlen);
CHECK_SIZE_AND_OFFSET(msghdr, msg_control);
CHECK_SIZE_AND_OFFSET(msghdr, msg_controllen);
CHECK_SIZE_AND_OFFSET(msghdr, msg_flags);

CHECK_TYPE_SIZE(cmsghdr);
CHECK_SIZE_AND_OFFSET(cmsghdr, cmsg_len);
CHECK_SIZE_AND_OFFSET(cmsghdr, cmsg_level);
CHECK_SIZE_AND_OFFSET(cmsghdr, cmsg_type);

COMPILER_CHECK(sizeof(__sanitizer_dirent) <= sizeof(dirent));
CHECK_SIZE_AND_OFFSET(dirent, d_ino);
#if SANITIZER_MAC
CHECK_SIZE_AND_OFFSET(dirent, d_seekoff);
#elif SANITIZER_FREEBSD
// There is no 'd_off' field on FreeBSD.
#else
CHECK_SIZE_AND_OFFSET(dirent, d_off);
#endif
CHECK_SIZE_AND_OFFSET(dirent, d_reclen);

#if SANITIZER_LINUX && !SANITIZER_ANDROID
COMPILER_CHECK(sizeof(__sanitizer_dirent64) <= sizeof(dirent64));
CHECK_SIZE_AND_OFFSET(dirent64, d_ino);
CHECK_SIZE_AND_OFFSET(dirent64, d_off);
CHECK_SIZE_AND_OFFSET(dirent64, d_reclen);
#endif

CHECK_TYPE_SIZE(ifconf);
CHECK_SIZE_AND_OFFSET(ifconf, ifc_len);
CHECK_SIZE_AND_OFFSET(ifconf, ifc_ifcu);

CHECK_TYPE_SIZE(pollfd);
CHECK_SIZE_AND_OFFSET(pollfd, fd);
CHECK_SIZE_AND_OFFSET(pollfd, events);
CHECK_SIZE_AND_OFFSET(pollfd, revents);

CHECK_TYPE_SIZE(nfds_t);

CHECK_TYPE_SIZE(sigset_t);

COMPILER_CHECK(sizeof(__sanitizer_sigaction) == sizeof(struct sigaction));
// Can't write checks for sa_handler and sa_sigaction due to them being
// preprocessor macros.
CHECK_STRUCT_SIZE_AND_OFFSET(sigaction, sa_mask);
CHECK_STRUCT_SIZE_AND_OFFSET(sigaction, sa_flags);
#if SANITIZER_LINUX
CHECK_STRUCT_SIZE_AND_OFFSET(sigaction, sa_restorer);
#endif

#if SANITIZER_LINUX
CHECK_TYPE_SIZE(__sysctl_args);
CHECK_SIZE_AND_OFFSET(__sysctl_args, name);
CHECK_SIZE_AND_OFFSET(__sysctl_args, nlen);
CHECK_SIZE_AND_OFFSET(__sysctl_args, oldval);
CHECK_SIZE_AND_OFFSET(__sysctl_args, oldlenp);
CHECK_SIZE_AND_OFFSET(__sysctl_args, newval);
CHECK_SIZE_AND_OFFSET(__sysctl_args, newlen);

CHECK_TYPE_SIZE(__kernel_uid_t);
CHECK_TYPE_SIZE(__kernel_gid_t);

#if SANITIZER_USES_UID16_SYSCALLS
CHECK_TYPE_SIZE(__kernel_old_uid_t);
CHECK_TYPE_SIZE(__kernel_old_gid_t);
#endif

CHECK_TYPE_SIZE(__kernel_off_t);
CHECK_TYPE_SIZE(__kernel_loff_t);
CHECK_TYPE_SIZE(__kernel_fd_set);
#endif

#if !SANITIZER_ANDROID
CHECK_TYPE_SIZE(wordexp_t);
CHECK_SIZE_AND_OFFSET(wordexp_t, we_wordc);
CHECK_SIZE_AND_OFFSET(wordexp_t, we_wordv);
CHECK_SIZE_AND_OFFSET(wordexp_t, we_offs);
#endif

CHECK_TYPE_SIZE(tm);
CHECK_SIZE_AND_OFFSET(tm, tm_sec);
CHECK_SIZE_AND_OFFSET(tm, tm_min);
CHECK_SIZE_AND_OFFSET(tm, tm_hour);
CHECK_SIZE_AND_OFFSET(tm, tm_mday);
CHECK_SIZE_AND_OFFSET(tm, tm_mon);
CHECK_SIZE_AND_OFFSET(tm, tm_year);
CHECK_SIZE_AND_OFFSET(tm, tm_wday);
CHECK_SIZE_AND_OFFSET(tm, tm_yday);
CHECK_SIZE_AND_OFFSET(tm, tm_isdst);
CHECK_SIZE_AND_OFFSET(tm, tm_gmtoff);
CHECK_SIZE_AND_OFFSET(tm, tm_zone);

#if SANITIZER_LINUX
CHECK_TYPE_SIZE(mntent);
CHECK_SIZE_AND_OFFSET(mntent, mnt_fsname);
CHECK_SIZE_AND_OFFSET(mntent, mnt_dir);
CHECK_SIZE_AND_OFFSET(mntent, mnt_type);
CHECK_SIZE_AND_OFFSET(mntent, mnt_opts);
CHECK_SIZE_AND_OFFSET(mntent, mnt_freq);
CHECK_SIZE_AND_OFFSET(mntent, mnt_passno);
#endif

CHECK_TYPE_SIZE(ether_addr);

#if (SANITIZER_LINUX || SANITIZER_FREEBSD) && !SANITIZER_ANDROID
CHECK_TYPE_SIZE(ipc_perm);
# if SANITIZER_FREEBSD
CHECK_SIZE_AND_OFFSET(ipc_perm, key);
CHECK_SIZE_AND_OFFSET(ipc_perm, seq);
# else
CHECK_SIZE_AND_OFFSET(ipc_perm, __key);
CHECK_SIZE_AND_OFFSET(ipc_perm, __seq);
# endif
CHECK_SIZE_AND_OFFSET(ipc_perm, uid);
CHECK_SIZE_AND_OFFSET(ipc_perm, gid);
CHECK_SIZE_AND_OFFSET(ipc_perm, cuid);
CHECK_SIZE_AND_OFFSET(ipc_perm, cgid);
#ifndef __GLIBC_PREREQ
#define __GLIBC_PREREQ(x, y) 0
#endif
//#if !defined(__aarch64__) || !SANITIZER_LINUX || __GLIBC_PREREQ (2, 21)
///* On aarch64 glibc 2.20 and earlier provided incorrect mode field.  */
#if !SANITIZER_LINUX || __GLIBC_PREREQ (2, 31)
CHECK_SIZE_AND_OFFSET(ipc_perm, mode);
#endif

CHECK_TYPE_SIZE(shmid_ds);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_perm);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_segsz);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_atime);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_dtime);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_ctime);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_cpid);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_lpid);
CHECK_SIZE_AND_OFFSET(shmid_ds, shm_nattch);
#endif

CHECK_TYPE_SIZE(clock_t);

#if SANITIZER_LINUX
CHECK_TYPE_SIZE(clockid_t);
#endif

#if !SANITIZER_ANDROID
CHECK_TYPE_SIZE(ifaddrs);
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_next);
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_name);
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_addr);
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_netmask);
#if SANITIZER_LINUX || SANITIZER_FREEBSD
// Compare against the union, because we can't reach into the union in a
// compliant way.
#ifdef ifa_dstaddr
#undef ifa_dstaddr
#endif
# if SANITIZER_FREEBSD
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_dstaddr);
# else
COMPILER_CHECK(sizeof(((__sanitizer_ifaddrs *)nullptr)->ifa_dstaddr) ==
               sizeof(((ifaddrs *)nullptr)->ifa_ifu));
COMPILER_CHECK(offsetof(__sanitizer_ifaddrs, ifa_dstaddr) ==
               offsetof(ifaddrs, ifa_ifu));
# endif // SANITIZER_FREEBSD
#else
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_dstaddr);
#endif // SANITIZER_LINUX
CHECK_SIZE_AND_OFFSET(ifaddrs, ifa_data);
#endif

#if SANITIZER_LINUX
COMPILER_CHECK(sizeof(__sanitizer_mallinfo) == sizeof(struct mallinfo));
#endif

#if !SANITIZER_ANDROID
CHECK_TYPE_SIZE(timeb);
CHECK_SIZE_AND_OFFSET(timeb, time);
CHECK_SIZE_AND_OFFSET(timeb, millitm);
CHECK_SIZE_AND_OFFSET(timeb, timezone);
CHECK_SIZE_AND_OFFSET(timeb, dstflag);
#endif

CHECK_TYPE_SIZE(passwd);
CHECK_SIZE_AND_OFFSET(passwd, pw_name);
CHECK_SIZE_AND_OFFSET(passwd, pw_passwd);
CHECK_SIZE_AND_OFFSET(passwd, pw_uid);
CHECK_SIZE_AND_OFFSET(passwd, pw_gid);
CHECK_SIZE_AND_OFFSET(passwd, pw_dir);
CHECK_SIZE_AND_OFFSET(passwd, pw_shell);

#if !SANITIZER_ANDROID
CHECK_SIZE_AND_OFFSET(passwd, pw_gecos);
#endif

#if SANITIZER_MAC
CHECK_SIZE_AND_OFFSET(passwd, pw_change);
CHECK_SIZE_AND_OFFSET(passwd, pw_expire);
CHECK_SIZE_AND_OFFSET(passwd, pw_class);
#endif


CHECK_TYPE_SIZE(group);
CHECK_SIZE_AND_OFFSET(group, gr_name);
CHECK_SIZE_AND_OFFSET(group, gr_passwd);
CHECK_SIZE_AND_OFFSET(group, gr_gid);
CHECK_SIZE_AND_OFFSET(group, gr_mem);

#if HAVE_RPC_XDR_H || HAVE_TIRPC_RPC_XDR_H
CHECK_TYPE_SIZE(XDR);
CHECK_SIZE_AND_OFFSET(XDR, x_op);
CHECK_SIZE_AND_OFFSET(XDR, x_ops);
CHECK_SIZE_AND_OFFSET(XDR, x_public);
CHECK_SIZE_AND_OFFSET(XDR, x_private);
CHECK_SIZE_AND_OFFSET(XDR, x_base);
CHECK_SIZE_AND_OFFSET(XDR, x_handy);
COMPILER_CHECK(__sanitizer_XDR_ENCODE == XDR_ENCODE);
COMPILER_CHECK(__sanitizer_XDR_DECODE == XDR_DECODE);
COMPILER_CHECK(__sanitizer_XDR_FREE == XDR_FREE);
#endif

#if SANITIZER_LINUX && !SANITIZER_ANDROID
COMPILER_CHECK(sizeof(__sanitizer_FILE) <= sizeof(FILE));
CHECK_SIZE_AND_OFFSET(FILE, _flags);
CHECK_SIZE_AND_OFFSET(FILE, _IO_read_ptr);
CHECK_SIZE_AND_OFFSET(FILE, _IO_read_end);
CHECK_SIZE_AND_OFFSET(FILE, _IO_read_base);
CHECK_SIZE_AND_OFFSET(FILE, _IO_write_ptr);
CHECK_SIZE_AND_OFFSET(FILE, _IO_write_end);
CHECK_SIZE_AND_OFFSET(FILE, _IO_write_base);
CHECK_SIZE_AND_OFFSET(FILE, _IO_buf_base);
CHECK_SIZE_AND_OFFSET(FILE, _IO_buf_end);
CHECK_SIZE_AND_OFFSET(FILE, _IO_save_base);
CHECK_SIZE_AND_OFFSET(FILE, _IO_backup_base);
CHECK_SIZE_AND_OFFSET(FILE, _IO_save_end);
CHECK_SIZE_AND_OFFSET(FILE, _markers);
CHECK_SIZE_AND_OFFSET(FILE, _chain);
CHECK_SIZE_AND_OFFSET(FILE, _fileno);
#endif

#if SANITIZER_LINUX && !SANITIZER_ANDROID
COMPILER_CHECK(sizeof(__sanitizer__obstack_chunk) <= sizeof(_obstack_chunk));
CHECK_SIZE_AND_OFFSET(_obstack_chunk, limit);
CHECK_SIZE_AND_OFFSET(_obstack_chunk, prev);
CHECK_TYPE_SIZE(obstack);
CHECK_SIZE_AND_OFFSET(obstack, chunk_size);
CHECK_SIZE_AND_OFFSET(obstack, chunk);
CHECK_SIZE_AND_OFFSET(obstack, object_base);
CHECK_SIZE_AND_OFFSET(obstack, next_free);

CHECK_TYPE_SIZE(cookie_io_functions_t);
CHECK_SIZE_AND_OFFSET(cookie_io_functions_t, read);
CHECK_SIZE_AND_OFFSET(cookie_io_functions_t, write);
CHECK_SIZE_AND_OFFSET(cookie_io_functions_t, seek);
CHECK_SIZE_AND_OFFSET(cookie_io_functions_t, close);
#endif

#if SANITIZER_LINUX || SANITIZER_FREEBSD
CHECK_TYPE_SIZE(sem_t);
#endif

#endif // SANITIZER_LINUX || SANITIZER_FREEBSD || SANITIZER_MAC

````

## Discrepancy Check

> This section verifies that applying the patch and then creating a new diff from the result reproduces the original input patch. This is a key integrity check.

### File: `libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc`
debug: Patch::from_texts: generating unified diff for 'libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc' (old len: 49626 bytes, new len: 49603 bytes, context: 3)
debug: Patch::from_texts: produced 1 hunk(s) for 'libsanitizer/sanitizer_common/sanitizer_platform_limits_posix.cc' (ends_with_newline=true)
