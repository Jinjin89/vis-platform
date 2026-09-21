#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/landlock.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

/* Fail closed. The worker gets read-only runtimes/inputs and one writable directory.
 * See https://www.kernel.org/doc/html/latest/userspace-api/landlock.html. */
static void fail(const char *step) { perror(step); exit(125); }
static void allow_path(int fd, const char *path, uint64_t rights, int optional) {
    int target = open(path, O_PATH | O_CLOEXEC);
    if (target < 0) { if (optional && errno == ENOENT) return; fail("sandbox path"); }
    struct stat st;
    if (fstat(target, &st) != 0) fail("sandbox stat");
    if (!S_ISDIR(st.st_mode)) rights &= LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_TRUNCATE;
    struct landlock_path_beneath_attr rule = { .allowed_access = rights, .parent_fd = target };
    if (syscall(SYS_landlock_add_rule, fd, LANDLOCK_RULE_PATH_BENEATH, &rule, 0)) fail("sandbox rule");
    close(target);
}
#define BLOCK(call) BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SYS_##call, 0, 1), BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO | EPERM)
static void restrict_syscalls(int allow_process_start) {
#if defined(__x86_64__)
    const unsigned int architecture = AUDIT_ARCH_X86_64;
#elif defined(__aarch64__)
    const unsigned int architecture = AUDIT_ARCH_AARCH64;
#else
#error Unsupported architecture
#endif
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, architecture, 1, 0),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, nr)),
#if defined(__x86_64__)
        BPF_JUMP(BPF_JMP|BPF_JGE|BPF_K, 0x40000000, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_KILL_PROCESS),
        BLOCK(fork), BLOCK(vfork),
#endif
        BLOCK(socket), BLOCK(socketpair), BLOCK(connect), BLOCK(bind), BLOCK(listen),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SYS_clone, 0, 5),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_STMT(BPF_ALU|BPF_AND|BPF_K, CLONE_THREAD),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, CLONE_THREAD, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SYS_clone3, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO | ENOSYS),
        BLOCK(ptrace), BLOCK(process_vm_readv), BLOCK(process_vm_writev),
        BLOCK(kill), BLOCK(tkill), BLOCK(tgkill), BLOCK(pidfd_open), BLOCK(pidfd_getfd), BLOCK(pidfd_send_signal),
        BLOCK(setns), BLOCK(unshare), BLOCK(mount), BLOCK(umount2), BLOCK(bpf), BLOCK(perf_event_open),
        BLOCK(io_uring_setup), BLOCK(keyctl), BLOCK(add_key), BLOCK(request_key), BLOCK(setsid), BLOCK(setpgid),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW),
    };
    if (allow_process_start) {
        for (size_t i = 0; i < sizeof(filter)/sizeof(filter[0]); i++) {
            if (filter[i].code == (BPF_JMP|BPF_JEQ|BPF_K) &&
                (filter[i].k == SYS_clone || filter[i].k == SYS_clone3
#if defined(__x86_64__)
                 || filter[i].k == SYS_fork || filter[i].k == SYS_vfork
#endif
                )) filter[i].k = UINT32_MAX;
        }
    }
    struct sock_fprog program = { .len = sizeof(filter)/sizeof(filter[0]), .filter = filter };
    if (syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, SECCOMP_FILTER_FLAG_TSYNC, &program)) fail("sandbox seccomp");
}
static void limit(int resource, rlim_t value) {
    struct rlimit bounds = {value, value};
    if (setrlimit(resource, &bounds)) fail("sandbox limit");
}
static void enter_sandbox(char **argv, int strict) {
    int abi = syscall(SYS_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 3) { fputs("Landlock ABI 3 is required.\n", stderr); exit(125); }
    uint64_t read = LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR;
    uint64_t all = read | LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_REMOVE_DIR | LANDLOCK_ACCESS_FS_REMOVE_FILE |
        LANDLOCK_ACCESS_FS_MAKE_CHAR | LANDLOCK_ACCESS_FS_MAKE_DIR | LANDLOCK_ACCESS_FS_MAKE_REG |
        LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO | LANDLOCK_ACCESS_FS_MAKE_BLOCK |
        LANDLOCK_ACCESS_FS_MAKE_SYM | LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE;
    struct landlock_ruleset_attr rules = { .handled_access_fs = all };
    int fd = syscall(SYS_landlock_create_ruleset, &rules, sizeof(rules), 0);
    if (fd < 0) fail("sandbox ruleset");
    const char *runtime[] = {"/usr/bin", "/usr/lib", "/usr/share/fonts", "/usr/share/fontconfig", "/usr/share/R", "/lib", "/lib64", "/etc/ld.so.cache", "/etc/localtime", "/etc/fonts", "/etc/R", "/dev/urandom", NULL};
    for (int i=0; runtime[i]; i++) allow_path(fd, runtime[i], read, 1);
    allow_path(fd, argv[1], read, 0);
    allow_path(fd, argv[2], read, 0);
    allow_path(fd, argv[3], all & ~(LANDLOCK_ACCESS_FS_MAKE_CHAR | LANDLOCK_ACCESS_FS_MAKE_BLOCK | LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO), 0);
    allow_path(fd, "/dev/null", LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_WRITE_FILE, 0);
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) fail("sandbox privileges");
    if (syscall(SYS_landlock_restrict_self, fd, 0)) fail("sandbox enter");
    close(fd);
    limit(RLIMIT_CPU, 30);
    limit(RLIMIT_AS, 1536UL * 1024 * 1024);
    limit(RLIMIT_FSIZE, 64UL * 1024 * 1024);
    limit(RLIMIT_NOFILE, 256);
    limit(RLIMIT_CORE, 0);
    restrict_syscalls(!strict);
}
/* R calls this after loading trusted runtime packages and before reading inputs
 * or evaluating generated code. Kernel restrictions cannot subsequently be removed. */
void vis_restrict(char **runtime, char **inputs, char **outputs) {
    char *args[] = {NULL, *runtime, *inputs, *outputs};
    enter_sandbox(args, 1);
}
int main(int argc, char **argv) {
    int abi = syscall(SYS_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    if (argc == 2 && !strcmp(argv[1], "--check")) { if (abi < 3) return 125; puts("landlock-seccomp"); return 0; }
    int bootstrap = argc > 1 && !strcmp(argv[1], "--bootstrap");
    if (bootstrap) { argv++; argc--; }
    if (argc < 5) return 125;
    enter_sandbox(argv, !bootstrap);
    execv(argv[4], &argv[4]);
    fail("sandbox execute");
}
