/* Read-only Mach VM scanner. Format reference: qwe11223/wechat-exporter-mac
 * 231884e core/key_extractor.py (MIT). No debugger attach or process signals.
 * Uses SDK structs, submap recursion, bounded windows and port cleanup.
 * User explicitly authorized implementing this optional flow; never autorun.
 */
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <libproc.h>
#include <sys/proc_info.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define CHUNK (4 * 1024 * 1024)
#define MAX_KEYS 1024
static char keys[MAX_KEYS][97];
static size_t count;

static void collect(const unsigned char *buf, size_t size) {
    for (size_t i = 0; i + 99 <= size; i++) {
        if (buf[i] != 'x' || buf[i + 1] != '\'' || buf[i + 98] != '\'') continue;
        size_t j;
        for (j = 2; j < 98 && isxdigit(buf[i + j]); j++);
        if (j != 98) continue;
        char value[97];
        for (j = 0; j < 96; j++) value[j] = tolower(buf[i + 2 + j]);
        value[96] = 0;
        for (j = 0; j < count && strcmp(keys[j], value); j++);
        if (j == count && count < MAX_KEYS) strcpy(keys[count++], value);
    }
}

static int scan(task_t task) {
    unsigned char *buf = malloc(CHUNK);
    if (!buf) return 5;
    struct timespec start, now;
    clock_gettime(CLOCK_MONOTONIC, &start);
    size_t total = 0;
    for (int pass = 0; pass < 2; pass++) {
        mach_vm_address_t address = 0;
        natural_t depth = 0;
        while (1) {
            clock_gettime(CLOCK_MONOTONIC, &now);
            if (now.tv_sec - start.tv_sec > 70 || total >= (size_t)8 * 1024 * 1024 * 1024) goto done;
            mach_vm_size_t size = 0;
            vm_region_submap_info_data_64_t info = {0};
            mach_msg_type_number_t info_count = VM_REGION_SUBMAP_INFO_COUNT_64;
            kern_return_t rc = mach_vm_region_recurse(task, &address, &size, &depth,
                (vm_region_recurse_info_t)&info, &info_count);
            if (rc != KERN_SUCCESS) break;
            if (info.is_submap) { depth++; continue; }
            int writable = (info.protection & VM_PROT_WRITE) != 0;
            if ((info.protection & VM_PROT_READ) && (pass == 0 ? writable : !writable)) {
                for (mach_vm_size_t offset = 0; offset < size;) {
                    clock_gettime(CLOCK_MONOTONIC, &now);
                    if (now.tv_sec - start.tv_sec > 70 || total >= (size_t)8 * 1024 * 1024 * 1024) goto done;
                    mach_vm_size_t wanted = size - offset < CHUNK ? size - offset : CHUNK, got = 0;
                    rc = mach_vm_read_overwrite(task, address + offset, wanted, (mach_vm_address_t)buf, &got);
                    total += wanted;
                    if (rc == KERN_SUCCESS) collect(buf, got);
                    if (wanted <= 99) break;
                    offset += wanted - 98;
                }
            }
            if (!size || address + size <= address) break;
            address += size;
        }
    }
done:
    memset(buf, 0, CHUNK); free(buf);
    return count ? 0 : 3;
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--self-test") == 0) {
        unsigned char fixture[200] = {0};
        fixture[50] = 'x'; fixture[51] = '\''; fixture[148] = '\'';
        memset(fixture + 52, 'a', 64); memset(fixture + 116, 'b', 32);
        collect(fixture, sizeof(fixture));
        if (count != 1 || strlen(keys[0]) != 96) return 5;
        puts("scanner-format-ok"); return 0;
    }
    if (argc != 3) return 2;
    char *end = NULL;
    long parsed = strtol(argv[1], &end, 10);
    if (!end || *end || parsed <= 1 || parsed > 2147483647) return 2;
    pid_t pid = (pid_t)parsed;
    long owner = strtol(argv[2], &end, 10);
    if (!end || *end || owner < 1) return 2;
    char path[PROC_PIDPATHINFO_MAXSIZE] = {0};
    const char *suffix = "/WeChat.app/Contents/MacOS/WeChat";
    if (proc_pidpath(pid, path, sizeof(path)) <= 0 || strlen(path) < strlen(suffix) ||
        strcmp(path + strlen(path) - strlen(suffix), suffix)) return 2;
    struct proc_bsdinfo bsd = {0};
    if (proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &bsd, sizeof(bsd)) != sizeof(bsd) || bsd.pbi_uid != owner) return 2;
    task_t task = MACH_PORT_NULL;
    if (task_for_pid(mach_task_self(), pid, &task) != KERN_SUCCESS) return 4;
    int rc = scan(task);
    mach_port_deallocate(mach_task_self(), task);
    if (rc) return rc;
    /* Retain multiple candidates for a salt rather than silently overwrite. */
    putchar('[');
    for (size_t i = 0; i < count; i++) printf("%s\"%s\"", i ? "," : "", keys[i]);
    puts("]"); memset(keys, 0, sizeof(keys));
    return 0;
}
