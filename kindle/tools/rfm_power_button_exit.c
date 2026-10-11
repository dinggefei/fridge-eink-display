#define _GNU_SOURCE

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/types.h>
#include <unistd.h>

#define MAX_INPUT_DEVICES 32

static volatile sig_atomic_t should_exit = 0;

static void request_exit(int signal_number)
{
    (void)signal_number;
    should_exit = 1;
}

static int is_numeric_name(const char *name)
{
    if (*name == '\0') {
        return 0;
    }
    while (*name != '\0') {
        if (!isdigit((unsigned char)*name)) {
            return 0;
        }
        ++name;
    }
    return 1;
}

static void resume_awesome(void)
{
    DIR *proc = opendir("/proc");
    struct dirent *entry;

    if (proc == NULL) {
        return;
    }

    while ((entry = readdir(proc)) != NULL) {
        char path[128];
        char comm[64];
        FILE *file;
        pid_t pid;

        if (!is_numeric_name(entry->d_name)) {
            continue;
        }
        if (snprintf(path, sizeof(path), "/proc/%s/comm", entry->d_name)
            >= (int)sizeof(path)) {
            continue;
        }
        file = fopen(path, "r");
        if (file == NULL) {
            continue;
        }
        if (fgets(comm, sizeof(comm), file) != NULL) {
            comm[strcspn(comm, "\r\n")] = '\0';
            if (strcmp(comm, "awesome") == 0) {
                pid = (pid_t)strtol(entry->d_name, NULL, 10);
                if (pid > 1) {
                    (void)kill(pid, SIGCONT);
                }
            }
        }
        fclose(file);
    }
    closedir(proc);
}

static int open_input_devices(struct pollfd *poll_fds)
{
    int count = 0;
    int index;

    for (index = 0; index < MAX_INPUT_DEVICES; ++index) {
        char path[64];
        int fd;

        (void)snprintf(path, sizeof(path), "/dev/input/event%d", index);
        fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0) {
            continue;
        }
        poll_fds[count].fd = fd;
        poll_fds[count].events = POLLIN;
        ++count;
    }
    return count;
}

static int dashboard_is_running(pid_t dashboard_pid)
{
    if (kill(dashboard_pid, 0) == 0) {
        return 1;
    }
    return errno == EPERM;
}

int main(int argc, char **argv)
{
    struct pollfd poll_fds[MAX_INPUT_DEVICES];
    pid_t dashboard_pid;
    int input_count;
    int index;

    if (argc != 2) {
        fprintf(stderr, "usage: %s DASHBOARD_PID\n", argv[0]);
        return 64;
    }
    dashboard_pid = (pid_t)strtol(argv[1], NULL, 10);
    if (dashboard_pid <= 1) {
        fprintf(stderr, "invalid dashboard pid\n");
        return 64;
    }

    (void)signal(SIGTERM, request_exit);
    (void)signal(SIGINT, request_exit);
    (void)signal(SIGHUP, request_exit);
    (void)prctl(PR_SET_PDEATHSIG, SIGTERM);

    input_count = open_input_devices(poll_fds);
    if (input_count == 0) {
        fprintf(stderr, "no readable input event devices\n");
        return 2;
    }

    while (!should_exit && dashboard_is_running(dashboard_pid)) {
        int ready = poll(poll_fds, (nfds_t)input_count, 1000);

        if (ready < 0) {
            if (errno == EINTR) {
                continue;
            }
            break;
        }
        if (ready == 0) {
            continue;
        }

        for (index = 0; index < input_count; ++index) {
            struct input_event event;
            ssize_t received;

            if ((poll_fds[index].revents & POLLIN) == 0) {
                continue;
            }
            while ((received = read(poll_fds[index].fd, &event,
                                    sizeof(event))) == (ssize_t)sizeof(event)) {
                if (event.type == EV_KEY && event.code == KEY_POWER
                    && event.value == 1) {
                    (void)kill(dashboard_pid, SIGTERM);
                    should_exit = 1;
                    break;
                }
            }
            if (should_exit) {
                break;
            }
        }
    }

    for (index = 0; index < input_count; ++index) {
        close(poll_fds[index].fd);
    }

    /* A second recovery path in case the shell daemon was killed before its
       EXIT trap could resume the Kindle window manager. */
    resume_awesome();
    return 0;
}
