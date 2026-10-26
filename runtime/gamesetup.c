// Game file setup (runtime/gamesetup.h). The picked folder is searched a few levels deep (dump tools nest the files):
// exefs/ is the folder with main and main.npdm, the RomFS either a romfs.bin image or the folder with bin/message.
// exefs/ is copied into <data root>/extracted (hard links where the file system allows), the RomFS image is copied
// or built (runtime/romfs_build.c), then the game code is recompiled from exefs/ (runtime/gamebuild.c).
#include "gamesetup.h"

#include <SDL3/SDL.h>
#include <ctype.h>
#include <errno.h>
#include <dirent.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef __linux__
#include <limits.h>
#endif

#include "gamebuild.h"
#include "gamelib.h"
#include "hle.h"
#include "paths.h"
#include "platform.h"
#include "romfs_build.h"

#define ROOT "extracted"  // (in the data root, the working directory)
// The two games (program ids, main.npdm's ACI0), any version. The 60 fps and wild battles options and the generator's
// instruction patches are addresses in the main: only the builds with address tables get them (game_build).
#define TITLE_EEVEE 0x0100187003A36000ull
#define TITLE_PIKACHU 0x010003F003A34000ull
static const uint8_t EEVEE_100[8] = {0x0a, 0x3f, 0x0d, 0x21, 0xe6, 0x7d, 0xad, 0x80};    // Let's Go, Eevee! v1.0.0 main
static const uint8_t PIKACHU_100[8] = {0x1c, 0x37, 0x56, 0x92, 0xde, 0x4f, 0x4b, 0x87};  // Let's Go, Pikachu! v1.0.0

static _Atomic int g_state;
static _Atomic float g_progress;
static _Atomic bool g_running;
static char g_folder[1024];

static bool image_ok(void);
static bool is_file(const char *p);
int setup_state(void) {  // (idle with a romfs.bin set up before that can't be read: say so, the setup is to be done again)
    if (g_state == SETUP_IDLE && !g_running && is_file(ROOT "/romfs.bin") && !image_ok()) return SETUP_FAIL_IMAGE;
    return g_state;
}
float setup_progress(void) { return g_progress; }
bool setup_running(void) { return g_running; }

static bool is_dir(const char *p) {
    struct stat st;
    return stat(p, &st) == 0 && S_ISDIR(st.st_mode);
}
static bool is_file(const char *p) {
    struct stat st;
    return stat(p, &st) == 0 && S_ISREG(st.st_mode);
}

static uint64_t program_id(const char *exefs) {
    char p[1100];
    snprintf(p, sizeof p, "%s/main.npdm", exefs);
    FILE *f = fopen(p, "rb");
    if (!f) return 0;
    uint64_t id = 0;
    uint8_t meta[0x80], aci[0x18];  // ACI0 (offset at META+0x70): the program id at +0x10
    if (fread(meta, 1, sizeof meta, f) == sizeof meta && !memcmp(meta, "META", 4) &&
        !fseek(f, *(uint32_t *)(meta + 0x70), SEEK_SET) && fread(aci, 1, sizeof aci, f) == sizeof aci &&
        !memcmp(aci, "ACI0", 4))
        id = *(uint64_t *)(aci + 0x10);
    fclose(f);
    return id;
}

static bool game_ok(const char *exefs) {
    uint64_t id = program_id(exefs);
    return id == TITLE_EEVEE || id == TITLE_PIKACHU;
}

int game_build(const char *exefs) {
    char p[1100];
    snprintf(p, sizeof p, "%s/main", exefs);
    FILE *f = fopen(p, "rb");
    if (!f) return GAME_BUILD_OTHER;
    uint8_t id[8] = {0};
    fseek(f, 0x40, SEEK_SET);  // (NSO header: the module id)
    size_t n = fread(id, 1, 8, f);
    fclose(f);
    uint64_t pid = program_id(exefs);
    if (n == 8 && !memcmp(id, EEVEE_100, 8) && pid == TITLE_EEVEE) return GAME_BUILD_EEVEE_100;
    if (n == 8 && !memcmp(id, PIKACHU_100, 8) && pid == TITLE_PIKACHU) return GAME_BUILD_PIKACHU_100;
    return GAME_BUILD_OTHER;
}

const char *game_version(const char *exefs) {
    static const struct { uint8_t id[8]; const char *v; } k[] = {
        {{0x0a, 0x3f, 0x0d, 0x21, 0xe6, 0x7d, 0xad, 0x80}, "1.0.0"},  // Eevee
        {{0x1c, 0x37, 0x56, 0x92, 0xde, 0x4f, 0x4b, 0x87}, "1.0.0"},  // Pikachu
        {{0xc2, 0x08, 0xdb, 0x6a, 0x4e, 0xf4, 0x36, 0x1f}, "1.0.2"},  // Pikachu (issue #1's log)
    };
    char p[1100];
    snprintf(p, sizeof p, "%s/main", exefs);
    uint8_t id[8] = {0};
    FILE *f = fopen(p, "rb");
    if (f) {
        fseek(f, 0x40, SEEK_SET);
        if (fread(id, 1, 8, f) != 8) memset(id, 0, 8);
        fclose(f);
    }
    for (size_t i = 0; i < sizeof k / sizeof *k; i++)
        if (!memcmp(id, k[i].id, 8)) return k[i].v;
    return "1.0.0";  // (a build not listed here)
}

const char *game_name(const char *exefs) {
    uint64_t id = program_id(exefs);
    return id == TITLE_EEVEE ? "Eevee" : id == TITLE_PIKACHU ? "Pikachu" : NULL;
}

// (a romfs.bin that isn't a readable RomFS - cut short, or another dump tool's format - stopped the game at its first
// read with 2002-6063, issue #31: set up again instead)
static bool image_ok(void) {
    char why[128];
    return romfs_image_ok(ROOT "/romfs.bin", why, sizeof why);
}

bool setup_ready(void) {
    return game_ok(ROOT "/exefs") && image_ok() && gamelib_present(ROOT);
}

bool setup_needs_build(void) {
    return game_ok(ROOT "/exefs") && image_ok() && !gamelib_present(ROOT);
}

typedef struct {
    char exefs[1024], romfs[1024], romfs_bin[1024];
    bool package;
    unsigned dirs_scanned, max_depth, access_errors;
} Found;

static void find_game(const char *dir, int depth, Found *f) {
    if (depth > 5 || (f->exefs[0] && (f->romfs[0] || f->romfs_bin[0]))) return;
    f->dirs_scanned++;
    if ((unsigned)depth > f->max_depth) f->max_depth = (unsigned)depth;
    char p[1100];
    snprintf(p, sizeof p, "%s/main.npdm", dir);
    if (!f->exefs[0] && is_file(p)) {
        snprintf(p, sizeof p, "%s/main", dir);
        if (is_file(p)) snprintf(f->exefs, sizeof f->exefs, "%s", dir);
    }
    snprintf(p, sizeof p, "%s/bin/message", dir);
    bool is_romfs_root = is_dir(p);
    if (!f->romfs[0] && is_romfs_root) snprintf(f->romfs, sizeof f->romfs, "%s", dir);
    snprintf(p, sizeof p, "%s/romfs.bin", dir);
    if (!f->romfs_bin[0] && is_file(p)) snprintf(f->romfs_bin, sizeof f->romfs_bin, "%s", p);

    // A recognized RomFS can contain tens of thousands of resource files. Never descend into
    // that tree while searching for an ExeFS elsewhere in the selected dump.
    if (is_romfs_root || (f->exefs[0] && (f->romfs[0] || f->romfs_bin[0]))) return;

    DIR *d = opendir(dir);
    if (!d) {
        if (errno == EACCES || errno == EPERM) f->access_errors++;
        return;
    }
    char sub[64][256];
    int nsub = 0;
    for (struct dirent *e; (e = readdir(d));) {
        const char *n = e->d_name;
        if (n[0] == '.') continue;
        size_t len = strlen(n);
        if (len > 4) {
            char ext[5];
            for (int i = 0; i < 4; i++) ext[i] = (char)tolower((unsigned char)n[len - 4 + i]);
            ext[4] = 0;
            if (!strcmp(ext, ".xci") || !strcmp(ext, ".nsp") || !strcmp(ext, ".nca") || !strcmp(ext, ".nsz") ||
                !strcmp(ext, ".xcz"))
                f->package = true;
        }
        snprintf(p, sizeof p, "%s/%s", dir, n);
        if (nsub < 64 && strcmp(n, "bin") && is_dir(p)) snprintf(sub[nsub++], sizeof sub[0], "%s", n);
    }
    closedir(d);
    // readdir order is filesystem-dependent. Sorting makes discovery deterministic and tends to
    // visit conventional "exefs" layouts before "romfs" resource trees.
    for (int i = 1; i < nsub; i++) {
        char key[256];
        snprintf(key, sizeof key, "%s", sub[i]);
        int j = i;
        while (j > 0 && strcmp(sub[j - 1], key) > 0) {
            snprintf(sub[j], sizeof sub[j], "%s", sub[j - 1]);
            j--;
        }
        snprintf(sub[j], sizeof sub[j], "%s", key);
    }
    for (int i = 0; i < nsub; i++) {
        snprintf(p, sizeof p, "%s/%s", dir, sub[i]);
        find_game(p, depth + 1, f);
        if (f->exefs[0] && (f->romfs[0] || f->romfs_bin[0])) break;
    }
}

// Progress is shown only for work with a measurable byte/function denominator. The UI hides
// the bar during discovery and RomFS metadata scanning.
static float g_phase0, g_phase1, g_code_base;
static bool g_scanning_romfs;
static void copy_progress(uint64_t done, uint64_t total) {
    if (g_scanning_romfs && done) g_state = SETUP_IMAGE;
    if (total) g_progress = g_phase0 + (g_phase1 - g_phase0) * (float)((double)done / (double)total);
}
static void build_progress(double f, const char *step) {
    g_progress = g_code_base + (1.0f - g_code_base) * (float)f;
    g_state = !strncmp(step, "Reading", 7) ? SETUP_READING : !strncmp(step, "Finishing", 9) ? SETUP_FINISHING
                                                                                           : SETUP_COMPILING;
}

#ifdef __linux__
static int effective_cpu_count(int host_cores) {
    int result = host_cores > 0 ? host_cores : 1;
    // cgroup v2 CPU quota: cpu.max contains "quota period" or "max period".
    FILE *f = fopen("/sys/fs/cgroup/cpu.max", "r");
    if (f) {
        char quota_text[64] = "";
        unsigned long long period = 0, quota = 0;
        if (fscanf(f, "%63s %llu", quota_text, &period) == 2 && period && strcmp(quota_text, "max")) {
            char *end = NULL;
            quota = strtoull(quota_text, &end, 10);
            if (end && !*end && quota) {
                unsigned long long count = quota / period;
                if (!count) count = 1;
                if (count < (unsigned long long)result) result = (int)count;
            }
        }
        fclose(f);
    }
    // cgroup v2 effective cpuset (for example "0-3,8"). Count only when the file parses.
    f = fopen("/sys/fs/cgroup/cpuset.cpus.effective", "r");
    if (f) {
        char text[4096] = "";
        if (fgets(text, sizeof text, f)) {
            int count = 0, valid = 1;
            char *p = text;
            while (*p && *p != '\n' && valid) {
                char *end = NULL;
                long first = strtol(p, &end, 10);
                if (end == p || first < 0) { valid = 0; break; }
                long last = first;
                p = end;
                if (*p == '-') {
                    p++;
                    last = strtol(p, &end, 10);
                    if (end == p || last < first) { valid = 0; break; }
                    p = end;
                }
                if (last - first > 4096 || count > INT_MAX - (int)(last - first + 1)) { valid = 0; break; }
                count += (int)(last - first + 1);
                if (*p == ',') p++;
                else if (*p && *p != '\n') valid = 0;
            }
            if (valid && count > 0 && count < result) result = count;
        }
        fclose(f);
    }
    return result > 0 ? result : 1;
}

static int effective_ram_mib(int host_ram_mib) {
    int result = host_ram_mib;
    FILE *f = fopen("/sys/fs/cgroup/memory.max", "r");
    if (f) {
        char text[64] = "";
        if (fgets(text, sizeof text, f) && strcmp(text, "max\n") && strcmp(text, "max")) {
            char *end = NULL;
            unsigned long long bytes = strtoull(text, &end, 10);
            if (end != text && bytes > 0) {
                unsigned long long mib = bytes / (1024ull * 1024ull);
                if (mib > 0 && (!result || mib < (unsigned long long)result)) result = (int)(mib > INT_MAX ? INT_MAX : mib);
            }
        }
        fclose(f);
    }
    return result > 0 ? result : host_ram_mib;
}
#endif

static bool build_code(void) {
    if (!gamebuild_available()) { g_state = SETUP_FAIL_TOOLS; return false; }
    int host_cores = SDL_GetNumLogicalCPUCores();
    int host_ram_mib = SDL_GetSystemRAM();
    if (host_cores < 1) host_cores = 1;
    int cores = host_cores, ram_mib = host_ram_mib;
#ifdef __linux__
    cores = effective_cpu_count(host_cores);
    ram_mib = effective_ram_mib(host_ram_mib);
#endif
    int ram_gb = ram_mib > 0 ? ram_mib / 1024 : 0;
    // The budget includes generator and compiler children. Use a conservative cap and allow
    // LARECOMP_BUILD_JOBS to reduce it further (never exceed detected capacity).
    int capacity = cores;
    if (ram_gb > 2 && ram_gb - 2 < capacity) capacity = ram_gb - 2;
    else if (ram_gb > 0 && ram_gb <= 2) capacity = 1;
    if (capacity > 16) capacity = 16;
    if (capacity < 1) capacity = 1;
    const char *jobs_env = getenv("LARECOMP_BUILD_JOBS");
    if (jobs_env && *jobs_env) {
        char *end = NULL;
        long requested = strtol(jobs_env, &end, 10);
        if (end != jobs_env && !*end && requested > 0 && requested < capacity) capacity = (int)requested;
    }
    GameBuildOpts o = {.progress = build_progress, .jobs = capacity, .cpu_cores = cores, .ram_mib = ram_mib,
                       .host_cores = host_cores, .host_ram_mib = host_ram_mib};
    LOG("[setup] resources: host_logical_cpu=%d host_ram_mib=%d effective_cpu=%d effective_ram_mib=%d "
        "global_child_budget=%d\n", host_cores, host_ram_mib, cores, ram_mib, capacity);
    char why[256] = "";
    g_state = SETUP_READING;
    if (!gamebuild_run(ROOT, &o, why, sizeof why)) {
        LOG("[setup] game code: %s\n", why);
        g_state = SETUP_FAIL_BUILD;
        return false;
    }
    return true;
}

static void *setup_thread(void *arg) {
    (void)arg;
    uint64_t setup_t0 = plat_now_ns();
    g_progress = 0;
    if (!g_folder[0]) {  // only the game code (files set up already, e.g. a new version of the app)
        LOG("[setup] the game files are set up, the game code is from another version: rebuilding it\n");
        g_code_base = 0.0f;
        if (build_code()) g_state = setup_ready() ? SETUP_DONE : SETUP_FAIL_BUILD;
        LOG("[setup] rebuild-only total_ms=%llu\n", (unsigned long long)((plat_now_ns() - setup_t0) / 1000000ull));
        g_running = false;
        return NULL;
    }
    const char *dry_run = getenv("LARECOMP_SETUP_DRY_RUN");
    if (dry_run && !strcmp(dry_run, "1")) {
        const char *redact = getenv("LARECOMP_SETUP_REDACT_PATHS");
        int rc = setup_dry_run(g_folder, redact && !strcmp(redact, "1"));
        if (rc == 0) g_state = SETUP_DRY_RUN_DONE;
        else if (rc == 3) g_state = SETUP_FAIL_PACKAGE;
        else if (rc == 2 || rc == 4) g_state = SETUP_FAIL_NOT_FOUND;
        else g_state = SETUP_FAIL_NOT_FOUND;
        LOG("[setup] env_dry_run_exit=%d total_ms=%llu; no setup writes/build processes run\n",
            rc, (unsigned long long)((plat_now_ns() - setup_t0) / 1000000ull));
        g_running = false;
        return NULL;
    }
    g_state = SETUP_LOOKING;
    Found f = {0};
    uint64_t find_t0 = plat_now_ns();
    find_game(g_folder, 0, &f);
    uint64_t find_ms = (plat_now_ns() - find_t0) / 1000000ull;
    LOG("[setup] find_game_ms=%llu dirs=%u max_depth=%u access_errors=%u\n",
        (unsigned long long)find_ms, f.dirs_scanned, f.max_depth, f.access_errors);
    LOG("[setup] %s: exefs %s, romfs %s, romfs.bin %s\n", g_folder, f.exefs[0] ? f.exefs : "-", f.romfs[0] ? f.romfs : "-",
        f.romfs_bin[0] ? f.romfs_bin : "-");
    if (!f.exefs[0] || (!f.romfs[0] && !f.romfs_bin[0])) g_state = f.package ? SETUP_FAIL_PACKAGE : SETUP_FAIL_NOT_FOUND;
    else if (!game_ok(f.exefs)) g_state = SETUP_FAIL_VERSION;
    else {
        // (the picked folder can't be our own copy: setting up again deletes that first)
        char a[4096], b[4096];
        mkdir(ROOT, 0755);
        if (realpath(f.exefs, a) && realpath(ROOT, b) && !strncmp(a, b, strlen(b)))
            snprintf(f.exefs, sizeof f.exefs, "%s", ""), g_state = SETUP_FAIL_NOT_FOUND;
    }
    if (g_state >= SETUP_FAIL_NOT_FOUND) {
        LOG("[setup] source validation failed total_ms=%llu\n",
            (unsigned long long)((plat_now_ns() - setup_t0) / 1000000ull));
        g_running = false;
        return NULL;
    }

    uint64_t cleanup_t0 = plat_now_ns();
    rt_remove_game_files(ROOT);  // (an earlier or interrupted setup's)
    mkdir(ROOT, 0755);
    LOG("[setup] cleanup_ms=%llu\n", (unsigned long long)((plat_now_ns() - cleanup_t0) / 1000000ull));
    g_state = SETUP_COPYING;
    g_phase0 = 0.02f, g_phase1 = 0.30f;
    uint64_t copy_t0 = plat_now_ns();
    bool ok = true;
    if (!strcmp(f.exefs, f.romfs)) {  // (a flat dump, main next to bin/: only the six code files, not the whole RomFS)
        static const char *const code[] = {"main", "main.npdm", "rtld", "sdk", "subsdk0", "subsdk1"};
        mkdir(ROOT "/exefs", 0755);
        for (size_t i = 0; ok && i < sizeof code / sizeof *code; i++) {
            char src[1100], dst[1100];
            snprintf(src, sizeof src, "%s/%s", f.exefs, code[i]);
            snprintf(dst, sizeof dst, ROOT "/exefs/%s", code[i]);
            ok = is_file(src) && romfs_copy_file(src, dst, copy_progress);
        }
    } else
        ok = romfs_copy_tree(f.exefs, ROOT "/exefs", copy_progress);
    LOG("[setup] exefs_copy_ms=%llu\n", (unsigned long long)((plat_now_ns() - copy_t0) / 1000000ull));
    uint64_t romfs_t0 = plat_now_ns();
    if (ok && f.romfs_bin[0]) {
        g_phase0 = 0.30f, g_phase1 = 0.45f;
        ok = romfs_copy_file(f.romfs_bin, ROOT "/romfs.bin", copy_progress);
        if (ok) LOG("[setup] romfs_source=existing-image transfer=hardlink-or-copy\n");
    } else if (ok) {
        g_state = SETUP_SCANNING;
        g_scanning_romfs = true;
        g_phase0 = 0.30f, g_phase1 = 0.65f;
        char why[256] = "";
        ok = romfs_build(f.romfs, ROOT "/romfs.bin", copy_progress, why, sizeof why);
        g_scanning_romfs = false;
        if (ok) LOG("[setup] romfs_source=directory image=constructed\n");
        if (!ok) LOG("[setup] romfs image: %s\n", why);
    }
    LOG("[setup] romfs_prepare_ms=%llu\n", (unsigned long long)((plat_now_ns() - romfs_t0) / 1000000ull));
    char why[128];
    if (!ok) g_state = SETUP_FAIL_COPY;
    else if (!romfs_image_ok(ROOT "/romfs.bin", why, sizeof why)) {
        LOG("[setup] the game data image %s: %s\n", f.romfs_bin[0] ? f.romfs_bin : "(built)", why);
        g_state = SETUP_FAIL_IMAGE;
    } else {
        g_code_base = 0.65f;
        if (build_code()) g_state = setup_ready() ? SETUP_DONE : SETUP_FAIL_BUILD;
    }
    LOG("[setup] %s total_ms=%llu\n", g_state == SETUP_DONE ? "ready" : "failed",
        (unsigned long long)((plat_now_ns() - setup_t0) / 1000000ull));
    g_running = false;
    return NULL;
}


/* Non-destructive diagnostic entry point, called before platform/UI initialization.
 * Exit codes: 0 valid source, 2 unrecognized/incompatible dump, 3 package requiring extraction, 4 access error. */
int setup_dry_run(const char *folder, bool redact_paths) {
    if (!folder || !*folder) {
        fprintf(stderr, "Usage: --setup-dry-run <folder> [--redact-paths]\n");
        return 64;
    }
    Found f = {0};
    uint64_t t0 = plat_now_ns();
    find_game(folder, 0, &f);
    const char *shown_root = redact_paths ? "<chemin masqué>" : folder;
    fprintf(stderr, "DRY RUN — aucun fichier modifié, aucun processus de build lancé\n");
    fprintf(stderr, "[setup-dry-run] find_game_ms=%llu dirs=%u max_depth=%u access_errors=%u\n",
            (unsigned long long)((plat_now_ns() - t0) / 1000000ull), f.dirs_scanned, f.max_depth, f.access_errors);
    if (!f.exefs[0] || (!f.romfs[0] && !f.romfs_bin[0])) {
        fprintf(stderr, "[setup-dry-run] source non reconnue: %s\n",
                f.package ? "package .xci/.nsp/.nca/.nsz/.xcz à extraire" : "exefs + romfs/romfs.bin manquants");
        if (f.package) return 3;
        return f.access_errors ? 4 : 2;
    }
    if (!game_ok(f.exefs)) {
        fprintf(stderr, "[setup-dry-run] ExeFS invalide ou jeu incompatible: %s\n",
                redact_paths ? "<chemin masqué>" : f.exefs);
        return f.access_errors ? 4 : 2;
    }
    if (f.romfs_bin[0]) {
        char why[160] = "";
        if (!romfs_image_ok(f.romfs_bin, why, sizeof why)) {
            fprintf(stderr, "[setup-dry-run] romfs.bin invalide: %s\n",
                    redact_paths ? "détail masqué" : why);
            return 2;
        }
    }
    fprintf(stderr, "[setup-dry-run] source valide; jeu=%s version=%s\n",
            game_name(f.exefs) ? game_name(f.exefs) : "Let's Go", game_version(f.exefs));
    fprintf(stderr, "[setup-dry-run] root=%s\n", shown_root);
    fprintf(stderr, "[setup-dry-run] exefs=%s\n", redact_paths ? "<chemin masqué>" : f.exefs);
    if (f.romfs_bin[0])
        fprintf(stderr, "[setup-dry-run] romfs_source=image; path=%s; action=copy-or-hardlink\n",
                redact_paths ? "<chemin masqué>" : f.romfs_bin);
    else
        fprintf(stderr, "[setup-dry-run] romfs_source=directory; path=%s; action=build-image\n",
                redact_paths ? "<chemin masqué>" : f.romfs);
    fprintf(stderr, "[setup-dry-run] actions prévues: préparer ExeFS, préparer/valider RomFS, générer et compiler le code du jeu\n");
    return 0;
}

void setup_start(const char *folder) {
    if (g_running) return;
    snprintf(g_folder, sizeof g_folder, "%s", folder ? folder : "");
    for (char *c = g_folder; *c; c++) if (*c == '\\') *c = '/';
    g_running = true;
    g_state = SETUP_LOOKING;
    pthread_t t;
    pthread_create(&t, NULL, setup_thread, NULL);
    pthread_detach(t);
}
