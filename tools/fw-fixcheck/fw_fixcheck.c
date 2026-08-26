/*
 * FWFixCheck v8 — did the FWIM speed clamp run, and what did the PHY say?
 *
 * The S800 fix lives in `FireWire Enabler`: OHCIFWIM is hooked immediately before it
 * hands the self-IDs up to `FWProcessSelfIDs`, reads the PHY, and clamps every self-ID
 * `sp` field to what a legacy segment can actually carry. Its counters sit in a block
 * marked `S8FX` / `v002` ... `ENDS` inside the patched code section, pre-initialised in
 * the file, so this scan distinguishes three states that look alike from the outside:
 *
 *   magic ABSENT           the patched Enabler is not resident at all. Most likely the
 *                          Mac OS ROM's own `pciclass,0c0010` parcel bound instead of
 *                          the extension, exactly the ambiguity FWPatchCheck v2 hit
 *                          with FWServicesLib. Says NOTHING about the clamp.
 *   magic present, calls 0 resident, but the hook never ran. Self-IDs are reaching the
 *                          family by some path that is not one of the two hooked sites.
 *   magic present, calls>0 the hook ran. Then `Max_Legacy_SPD` and the clamp ceiling
 *                          say what it decided, and `clamped` says what it changed.
 *
 * It also re-runs FWPatchCheck's FWServicesLib scan, because the S800 fix REQUIRES
 * `FireWire Support` to be back to STOCK. A PATCHED count above zero here means the old
 * global S400 clamp is still installed and is masking the new one — the run is void.
 *
 * Finally it reads PHY base registers 2 and 6 itself, so the log carries the PHY's own
 * view next to what the hook recorded. Disagreement between the two is meaningful: the
 * hook reads at self-ID time, this reads now.
 *
 * Read-only apart from the PhyControl read requests that a PHY read inherently needs.
 * No page selection, so base register 7 is never written.
 */
#include <MacTypes.h>
#include <Quickdraw.h>
#include <Fonts.h>
#include <Windows.h>
#include <Events.h>
#include <Dialogs.h>
#include <TextEdit.h>
#include <TextUtils.h>
#include <Memory.h>

#include <OSUtils.h>            /* TickCount, Delay                                 */
#include <Devices.h>
#include <NameRegistry.h>
#include <PCI.h>              /* ExpMgrConfigReadWord -- config cycles never fault */
#include <CodeFragments.h>
#include <Folders.h>
#include <Processes.h>
#include <Files.h>
#include <Sound.h>
#include <Timer.h>            /* Microseconds -- declared here, NOT in OSUtils.h  */

#include <string.h>


/* ---- tunables ------------------------------------------------------------ */

#define kLingerTicks     (60 * 60)
#define kMaxSummary      96
#define kLinesPerPage     22


/* ---- OHCI 1.1 register offsets ------------------------------------------- *
 * "Set" aliases are read here only; reading one returns the current value.   */

#define kOHCIVersion     0x000
#define kOHCIBusOptions  0x020
#define kOHCIGUIDHi      0x024
#define kOHCIGUIDLo      0x028
#define kOHCIHCControl   0x050
#define kOHCISelfIDBuf   0x064
#define kOHCISelfIDCount 0x068
#define kOHCIIntEvent    0x080
#define kOHCILinkControl 0x0E0
#define kOHCINodeID      0x0E8


/* ---- Pascal-string helpers ----------------------------------------------- */

static void PStrCat(Str255 dst, const char *src)
{
    short len = dst[0];
    while (*src && len < 255) dst[++len] = (unsigned char)*src++;
    dst[0] = (unsigned char)len;
}

static void PStrCatCh(Str255 dst, char c)
{
    if (dst[0] < 255) dst[++dst[0]] = (unsigned char)c;
}

static void PStrCatNum(Str255 dst, long n)
{
    Str255 num;
    short  i;
    NumToString(n, num);
    for (i = 1; i <= num[0] && dst[0] < 255; i++) dst[++dst[0]] = num[i];
}

static void PStrCatHexN(Str255 dst, unsigned long v, short digits)
{
    static const char hx[] = "0123456789ABCDEF";
    short i;
    for (i = (short)((digits - 1) * 4); i >= 0; i -= 4)
        if (dst[0] < 255) dst[++dst[0]] = (unsigned char)hx[(v >> i) & 0xF];
}

static void PStrCatPStr(Str255 dst, const unsigned char *p)
{
    short i;
    for (i = 1; i <= p[0] && dst[0] < 255; i++) dst[++dst[0]] = p[i];
}


/* ---- log file, with fallback (same design as fw-regdump v2 / fw-phydump) -- */

typedef struct {
    short   refNum;
    short   vRefNum;
    Boolean open;
    Str255  where;
    OSErr   lastErr;
} LogFile;

static LogFile gLog;

static Boolean LogTryDir(short vRefNum, long dirID, const char *label)
{
    FSSpec spec;
    OSErr  err;
    Str255 volName;

    gLog.lastErr = noErr;
    err = FSMakeFSSpec(vRefNum, dirID, "\pFWFixCheck_v8.log", &spec);
    if (err != noErr && err != fnfErr) { gLog.lastErr = err; return false; }
    if (spec.name[0] == 0)             { gLog.lastErr = err ? err : paramErr; return false; }

    (void)FSpDelete(&spec);
    err = FSpCreate(&spec, 'ttxt', 'TEXT', smSystemScript);
    if (err != noErr && err != dupFNErr) { gLog.lastErr = err; return false; }
    err = FSpOpenDF(&spec, fsWrPerm, &gLog.refNum);
    if (err != noErr) { gLog.lastErr = err; return false; }

    gLog.vRefNum = spec.vRefNum;
    gLog.open = true;
    SetEOF(gLog.refNum, 0);

    {
        HParamBlockRec pb;
        memset(&pb, 0, sizeof(pb));
        volName[0] = 0;
        pb.volumeParam.ioNamePtr  = volName;
        pb.volumeParam.ioVRefNum  = spec.vRefNum;
        pb.volumeParam.ioVolIndex = 0;
        if (PBHGetVInfoSync(&pb) != noErr) volName[0] = 0;
    }
    gLog.where[0] = 0;
    PStrCat(gLog.where, label);
    PStrCat(gLog.where, " on \"");
    if (volName[0]) PStrCatPStr(gLog.where, volName); else PStrCatCh(gLog.where, '?');
    PStrCatCh(gLog.where, '"');
    return true;
}

static void LogOpen(void)
{
    short vRefNum;
    long  dirID;

    gLog.open = false;
    gLog.where[0] = 0;
    gLog.lastErr = noErr;

    {
        ProcessSerialNumber psn;
        ProcessInfoRec      info;
        FSSpec              appSpec;
        memset(&info, 0, sizeof(info));
        memset(&appSpec, 0, sizeof(appSpec));
        info.processInfoLength = sizeof(info);
        info.processName       = NULL;
        info.processAppSpec    = &appSpec;
        if (GetCurrentProcess(&psn) == noErr &&
            GetProcessInformation(&psn, &info) == noErr &&
            LogTryDir(appSpec.vRefNum, appSpec.parID, "next to the app"))
            return;
    }
    if (FindFolder(kOnSystemDisk, kSystemFolderType, kDontCreateFolder,
                   &vRefNum, &dirID) == noErr &&
        LogTryDir(vRefNum, dirID, "System Folder"))
        return;
    if (LogTryDir(0, fsRtDirID, "startup volume root")) return;

    gLog.where[0] = 0;
    PStrCat(gLog.where, "NOT WRITTEN");
}

static void LogLine(Str255 s)
{
    long count;
    unsigned char cr = '\r';
    if (!gLog.open) return;
    count = s[0];
    if (count > 0) FSWrite(gLog.refNum, &count, &s[1]);
    count = 1;
    FSWrite(gLog.refNum, &count, &cr);
}

static void LogText(const char *s)
{
    Str255 line;
    line[0] = 0;
    PStrCat(line, s);
    LogLine(line);
}

static void LogClose(void)
{
    if (!gLog.open) return;
    FSClose(gLog.refNum);
    FlushVol(NULL, gLog.vRefNum);
    gLog.open = false;
}

static Str255 gSummary[kMaxSummary];
static short  gSummaryCount = 0;

static void Summary(Str255 s)
{
    LogLine(s);
    if (gSummaryCount < kMaxSummary)
        BlockMoveData(s, gSummary[gSummaryCount++], (Size)(s[0] + 1));
}

static void SummaryText(const char *s)
{
    Str255 line;
    line[0] = 0;
    PStrCat(line, s);
    Summary(line);
}






/* ---- reading the PHY ourselves (lifted from fw-phydump, writes nothing) --- */

#define kPhyTimeoutUS    20000UL
#define kOHCIPhyControl  0x0EC
#define kPhyRdDone       0x80000000UL
#define kPhyRdReg        0x00008000UL
#define kPhyRdAddrShift  24
#define kPhyRdDataShift  16
#define kPhyRegAddrShift 8

static RegEntryID    gNode;
static Boolean       gHaveNode = false;
static unsigned long gAAPLAddress = 0;
static unsigned char gLocalGUID[8];
static Boolean       gHaveGUID = false;
static char          gNodePath[256];
static unsigned long gOhciVersion = 0;
static Boolean       gOracleOK = false;

static Boolean GetPropU32(const RegEntryID *id, const char *name, unsigned long *out)
{
    unsigned long        v = 0;
    RegPropertyValueSize sz = sizeof(v);
    if (RegistryPropertyGet((RegEntryID *)id, (RegPropertyName *)name, &v, &sz) != noErr)
        return false;
    if (sz != sizeof(v)) return false;
    *out = v;
    return true;
}

/* Walk the registry for the node with device_type "ieee1394" / class-code 0x0C0010.
 * kRegIterContinue, not the relationship — see [[reference_os9_nameregistry_iterate]]. */
static void FindFireWireNode(void)
{
    RegEntryIter cookie;
    RegEntryID   entry;
    Boolean      done = false;

    if (RegistryEntryIterateCreate(&cookie) != noErr) return;
    for (;;) {
        unsigned long        cc = 0;
        char                 dt[32];
        RegPropertyValueSize sz;
        OSStatus             err;

        RegistryEntryIDInit(&entry);
        err = RegistryEntryIterate(&cookie, kRegIterContinue, &entry, &done);
        if (err != noErr || done) { RegistryEntryIDDispose(&entry); break; }

        dt[0] = 0;
        sz = sizeof(dt) - 1;
        if (RegistryPropertyGet(&entry, "device_type", dt, &sz) == noErr) {
            if (sz > sizeof(dt) - 1) sz = sizeof(dt) - 1;
            dt[sz] = 0;
        } else {
            dt[0] = 0;
        }
        (void)GetPropU32(&entry, "class-code", &cc);

        if (strcmp(dt, "ieee1394") == 0 || (cc & 0x00FFFFFFUL) == 0x000C0010UL) {
            RegPropertyValueSize gsz = sizeof(gLocalGUID);
            RegPathNameSize      psz = 0;

            (void)GetPropU32(&entry, "AAPL,address", &gAAPLAddress);
            gHaveGUID = (RegistryPropertyGet(&entry, "local-guid", gLocalGUID, &gsz) == noErr
                         && gsz == sizeof(gLocalGUID));
            memset(gNodePath, 0, sizeof(gNodePath));
            if (RegistryEntryToPathSize(&entry, &psz) == noErr &&
                psz > 0 && psz < (RegPathNameSize)sizeof(gNodePath))
                (void)RegistryCStrEntryToPath(&entry, gNodePath, psz);

            gNode = entry;             /* keep it; do NOT dispose */
            gHaveNode = true;
            break;
        }
        RegistryEntryIDDispose(&entry);
    }
    RegistryEntryIterateDispose(&cookie);
}


/* ---- MMIO, with byte order CALIBRATED rather than assumed ---------------- */

static volatile unsigned char *gBase = NULL;
static Boolean gSwap = false;          /* set by the GUID oracle              */

static unsigned long Swap32(unsigned long v)
{
    return ((v & 0x000000FFUL) << 24) | ((v & 0x0000FF00UL) << 8) |
           ((v & 0x00FF0000UL) >> 8)  | ((v & 0xFF000000UL) >> 24);
}

static unsigned long RawRead32(unsigned long off)
{
    return *(volatile unsigned long *)(gBase + off);
}

static void RawWrite32(unsigned long off, unsigned long v)
{
    *(volatile unsigned long *)(gBase + off) = v;
}

static unsigned long Read32(unsigned long off)
{
    unsigned long v = RawRead32(off);
    return gSwap ? Swap32(v) : v;
}

static void Write32(unsigned long off, unsigned long v)
{
    RawWrite32(off, gSwap ? Swap32(v) : v);
}

/* Elapsed microseconds since `start`. */
static unsigned long ElapsedUS(const UnsignedWide *start)
{
    UnsignedWide now;
    Microseconds(&now);
    /* 32-bit low difference is ample for our millisecond-scale bounds and is
     * correct across a single low-word wrap. */
    return now.lo - start->lo;
}


/* ---- PHY register access via OHCI PhyControl ----------------------------- */

static long gPhyTimeouts = 0;

/* Returns 0..255 on success, -1 on timeout / address mismatch. */
static short PhyRead(unsigned char addr)
{
    UnsignedWide  t0;
    unsigned long v;

    Write32(kOHCIPhyControl, kPhyRdReg | ((unsigned long)(addr & 0x0F) << kPhyRegAddrShift));
    Microseconds(&t0);
    for (;;) {
        v = Read32(kOHCIPhyControl);
        if (v & kPhyRdDone) {
            if (((v >> kPhyRdAddrShift) & 0x0F) == (addr & 0x0F))
                return (short)((v >> kPhyRdDataShift) & 0xFF);
            /* someone else's completion — keep waiting within the bound */
        }
        if (ElapsedUS(&t0) > kPhyTimeoutUS) { gPhyTimeouts++; return -1; }
    }
}




/* Calibrate gSwap against the GUID the Name Registry already published, so the
 * byte order is MEASURED rather than assumed. Read-only. */
static Boolean OracleCalibrate(void)
{
    unsigned long wantHi, wantLo, rawHi, rawLo;

    if (!gHaveGUID) return false;
    wantHi = ((unsigned long)gLocalGUID[0] << 24) | ((unsigned long)gLocalGUID[1] << 16) |
             ((unsigned long)gLocalGUID[2] << 8)  |  (unsigned long)gLocalGUID[3];
    wantLo = ((unsigned long)gLocalGUID[4] << 24) | ((unsigned long)gLocalGUID[5] << 16) |
             ((unsigned long)gLocalGUID[6] << 8)  |  (unsigned long)gLocalGUID[7];

    gSwap = false;
    rawHi = RawRead32(0x024);
    rawLo = RawRead32(0x028);
    if (rawHi == wantHi && rawLo == wantLo)             gSwap = false;
    else if (Swap32(rawHi) == wantHi && Swap32(rawLo) == wantLo) gSwap = true;
    else return false;

    gOhciVersion = Read32(0x000);
    return ((gOhciVersion >> 16) & 0xFF) == 1;
}


/* ---- the scan ------------------------------------------------------------ */

/* FWServicesLib's speed-map builder. For the S800 fix this MUST read unpatched:
 * the old global clamp has to be gone or it masks the new per-bus one. */
#define kWordOld  0x548497BEUL    /* rlwinm r4,r4,18,30,31 - STOCK, what we want now */
#define kWordNew  0x548497BCUL    /* rlwinm r4,r4,18,30,30 - the old global S400 clamp */
#define kWordPre  0x80880000UL    /* lwz  r4,0(r8)                                    */
#define kWordPost 0x98980008UL    /* stb  r4,8(r24)                                   */

/* The FWIM hook's scratch block, laid down by patch-firewire-enabler.py (v003). */
#define kMagic0   0x53384658UL    /* 'S8FX' */
#define kMagicVer 0x76300000UL    /* 'v0..' - the build number is read, not
                                    matched, so the checker survives an
                                    extension bump without a rebuild */
#define kMagicEnd 0x454E4453UL    /* 'ENDS' at word 16 */
#define kWCalls     2             /* word indices from the block base */
#define kWPhy2      3
#define kWGCeil     4
#define kWMode      5
#define kWTotal     6
#define kWLenB      7
#define kWLast      8
#define kWLocalID   9
#define kWNRemote  10
#define kWNTable   11
#define kWPort0    12             /* 12,13,14 */
#define kWReg7     15
#define kWTable    17             /* 17..20 */
#define kWOrder    21
#define kWNodes    24             /* 24..27: (phy_ID<<16)|(own sp<<8)|ceiling */
#define kWNodeN    28
#define kWCapped   29            /* CLAMP refused an over-long buffer */
#define kWords     32

#define kMaxHits  4

static short gOld = 0, gNew = 0, gBlocks = 0;
static unsigned long gBlockAt[kMaxHits];
static unsigned long gC[kMaxHits][kWords];

static const char *SpeedName(unsigned long sp)
{
    switch (sp & 3) {
    case 0:  return "S100";
    case 1:  return "S200";
    case 2:  return "S400";
    default: return "S800";
    }
}

static const char *StateName(unsigned long st)
{
    switch (st & 3) {
    case 0:  return "not-present";
    case 1:  return "not-connected";
    case 2:  return "PARENT";
    default: return "CHILD";
    }
}

static void ReportBlock(short i)
{
    unsigned long *c = gC[i];
    Str255 line;
    short  k;

    line[0] = 0;
    PStrCat(line, "FWIM block @0x"); PStrCatHexN(line, gBlockAt[i], 8);
    PStrCat(line, "   build ");
    PStrCatCh(line, (char)((c[1] >> 24) & 0xFF)); PStrCatCh(line, (char)((c[1] >> 16) & 0xFF));
    PStrCatCh(line, (char)((c[1] >> 8) & 0xFF));  PStrCatCh(line, (char)(c[1] & 0xFF));
    PStrCat(line, "   port->node ordering: ");
    PStrCat(line, c[kWOrder] ? "DESCEND" : "ASCEND");
    Summary(line);

    line[0] = 0;
    PStrCat(line, "  hook calls ");    PStrCatNum(line, (long)c[kWCalls]);
    PStrCat(line, "   clamped last "); PStrCatNum(line, (long)c[kWLast]);
    PStrCat(line, "   total ");        PStrCatNum(line, (long)c[kWTotal]);
    Summary(line);

    if (c[kWCalls] == 0) {
        SummaryText("  *** RESIDENT BUT NEVER RAN. ***");
        SummaryText("  Self-IDs are reaching the family by an unhooked path.");
        return;
    }

    line[0] = 0;
    PStrCat(line, "  PHY reg2 0x");    PStrCatHexN(line, c[kWPhy2], 2);
    PStrCat(line, " (Num_Ports ");     PStrCatNum(line, (long)(c[kWPhy2] & 0x1F));
    PStrCat(line, ")   reg7 0x");      PStrCatHexN(line, c[kWReg7], 2);
    PStrCat(line, "   localID ");      PStrCatNum(line, (long)c[kWLocalID]);
    Summary(line);

    line[0] = 0;
    PStrCat(line, "  remote nodes ");  PStrCatNum(line, (long)c[kWNRemote]);
    PStrCat(line, "   mapped to ports "); PStrCatNum(line, (long)c[kWNTable]);
    PStrCat(line, "   global ceiling "); PStrCat(line, SpeedName(c[kWGCeil]));
    Summary(line);

    for (k = 0; k < 3; k++) {
        unsigned long v = c[kWPort0 + k];
        line[0] = 0;
        PStrCat(line, "  port "); PStrCatNum(line, (long)k); PStrCat(line, ": ");
        if (v == 0xFFFFFFFFUL) {
            PStrCat(line, "not reached (loop never got here)");
        } else if ((v & 0xFF) == 0xF0) {
            PStrCat(line, StateName((v >> 16) & 3));
            PStrCat(line, "  - skipped, port registers not read");
        } else {
            PStrCat(line, StateName((v >> 16) & 3));
            PStrCat(line, ((v >> 8) & 1) ? "  beta" : "  legacy(DS)");
            PStrCat(line, "  negotiated ");
            PStrCat(line, SpeedName(v & 3));
        }
        Summary(line);
    }

    for (k = 0; k < (short)c[kWNodeN] && k < 4; k++) {
        unsigned long e = c[kWNodes + k];
        line[0] = 0;
        PStrCat(line, "  self-ID node "); PStrCatNum(line, (long)((e >> 16) & 0x3F));
        PStrCat(line, "  its own sp ");   PStrCat(line, SpeedName(e >> 8));
        PStrCat(line, "  ->  ceiling ");  PStrCat(line, SpeedName(e));
        if (((e >> 8) & 3) == 3)
            PStrCat(line, "   (the 1394b device)");
        Summary(line);
    }

    if (c[kWCapped]) {
        line[0] = 0;
        PStrCat(line, "  *** OVER-LONG SELF-ID BUFFER REFUSED ");
        PStrCatNum(line, (long)c[kWCapped]);
        PStrCat(line, " TIME(S). ***");
        Summary(line);
        SummaryText("  The FWIM handed the hook a buffer longer than a self-ID buffer can");
        SummaryText("  be. It was refused untouched rather than walked. Report this: it is");
        SummaryText("  the condition that could previously have corrupted memory.");
    }

    if (c[kWMode]) {
        for (k = 0; k < (short)c[kWNTable] && k < 4; k++) {
            unsigned long e = c[kWTable + k];
            line[0] = 0;
            PStrCat(line, "  node "); PStrCatNum(line, (long)((e >> 8) & 0x3F));
            PStrCat(line, " ceiling "); PStrCat(line, SpeedName(e));
            Summary(line);
        }
        SummaryText("  *** PER-CONNECTION. Each node is clamped to its own port. ***");
        SummaryText("  ORDERING CHECK, only meaningful with two devices at different");
        SummaryText("  speeds: the node whose OWN sp is S800 is the 1394b device. If its");
        SummaryText("  ceiling came out S400, the port->node ordering is backwards and the");
        SummaryText("  other variant is the right one. Nothing will have failed visibly:");
        SummaryText("  a real 1394a device limits itself, so the only casualty is the");
        SummaryText("  1394b drive quietly losing S800.");
    } else {
        line[0] = 0;
        PStrCat(line, "  *** GLOBAL FALLBACK: everything clamped to ");
        PStrCat(line, SpeedName(c[kWGCeil]));
        PStrCat(line, ". ***");
        Summary(line);
        if (c[kWNRemote] == 0 && c[kWNTable] == 0) {
            SummaryText("  Nothing is attached: no node to map, and the only self-ID is our");
            SummaryText("  own. Clamping it to the default S400 costs nothing with no bus");
            SummaryText("  traffic and is recomputed on the next reset. EXPECTED for run 1.");
        }
        else if (c[kWNTable] == 0)
            SummaryText("  No port was mapped: PHY unreadable, or >3 ports.");
        else if (c[kWNTable] != c[kWNRemote]) {
            SummaryText("  Not a star: some node is not directly attached to this PHY, so");
            SummaryText("  at least one hop is one this PHY cannot measure. S400 is the");
            SummaryText("  CORRECT answer here, not a limitation: a legacy hop deeper in");
            SummaryText("  the tree is invisible in the self-IDs, which is the very defect");
            SummaryText("  this patch exists to work around.");
        }
        else
            SummaryText("  Child count did not match our own phy_ID; tree not as expected.");
    }
}


static void ScanSystemHeap(void)
{
    THz            zone = SystemZone();
    unsigned long *p, *lim;
    unsigned long  lo, hi;
    Str255         line;
    short          i, j;

    LogText("=========================================================");
    LogText("  SYSTEM HEAP SCAN");
    LogText("    1. the FWIM hook's counter block  'S8FX' 'v0nn' .. 'ENDS'");
    LogText("    2. FWServicesLib's speed-map instruction, which must be STOCK");
    LogText("=========================================================");

    if (zone == NULL) { SummaryText("SystemZone() returned NULL. VOID."); return; }
    lo = (unsigned long)zone;
    hi = (unsigned long)zone->bkLim;
    if (hi <= lo || (hi - lo) > 0x20000000UL) {
        line[0] = 0;
        PStrCat(line, "System zone bounds implausible: 0x");
        PStrCatHexN(line, lo, 8); PStrCat(line, " .. 0x"); PStrCatHexN(line, hi, 8);
        Summary(line);
        SummaryText("Refusing to scan. VOID.");
        return;
    }

    line[0] = 0;
    PStrCat(line, "System heap 0x"); PStrCatHexN(line, lo, 8);
    PStrCat(line, " .. 0x");        PStrCatHexN(line, hi, 8);
    PStrCat(line, "  ");            PStrCatNum(line, (long)((hi - lo) >> 10));
    PStrCat(line, " KB");
    Summary(line);

    lim = (unsigned long *)(hi - 256);
    for (p = (unsigned long *)((lo + 3) & ~3UL); p < lim; p++) {
        if (p[0] == kMagic0 && (p[1] & 0xFFFF0000UL) == kMagicVer &&
            p[16] == kMagicEnd) {
            if (gBlocks < kMaxHits) {
                gBlockAt[gBlocks] = (unsigned long)p;
                for (j = 0; j < kWords; j++) gC[gBlocks][j] = p[j];
                gBlocks++;
            }
            continue;
        }
        if ((p[1] == kWordOld || p[1] == kWordNew) &&
            p[0] == kWordPre && p[2] == kWordPost) {
            if (p[1] == kWordOld) gOld++; else gNew++;
        }
    }

    SummaryText("---------------------------------------------------------");
    line[0] = 0;
    PStrCat(line, "FWServicesLib speed-map copies:  STOCK ");
    PStrCatNum(line, (long)gOld);
    PStrCat(line, "   OLD-CLAMP ");
    PStrCatNum(line, (long)gNew);
    Summary(line);
    if (gNew > 0) {
        SummaryText("*** THE OLD GLOBAL S400 CLAMP IS STILL RESIDENT. ***");
        SummaryText("Put the STOCK FireWire Support back before judging this run.");
        SummaryText("Everything below is masked by it. VOID.");
    }

    SummaryText("---------------------------------------------------------");
    if (gBlocks == 0) {
        SummaryText("*** FWIM COUNTER BLOCK NOT FOUND. ***");
        SummaryText("The patched FireWire Enabler is not resident. Either it is not");
        SummaryText("installed, or the Mac OS ROM's own pciclass,0c0010 parcel bound");
        SummaryText("instead of the extension. Says NOTHING about the clamp itself.");
        return;
    }

    for (i = 0; i < gBlocks; i++) ReportBlock(i);
}



/* ---- is the controller's memory space actually decoding? ---------------- *
 * v2 walked straight into MMIO at AAPL,address and took a Type 1 bus error the
 * one time it mattered: the patched Enabler had failed to load, nothing had
 * claimed the controller, and its memory space was not live.
 *
 * v3 guarded that by looking for a bound FWIM in the Device Manager unit table.
 * That was wrong. FWRegDump on this very machine reports "FireWire drivers bound:
 * 0 of 2 controllers" with STOCK extensions and FireWire working perfectly: the
 * FWIM is a CFM fragment loaded by the FireWire expert, never a Device Manager
 * unit, so GetDriverInformation can never see it. The guard was a false negative
 * that suppressed the PHY read in every case, healthy or not.
 *
 * The honest test is the one the hardware answers: PCI configuration space,
 * command register bit 1, Memory Space Enable. Config cycles reach the device
 * through the bridge whether or not its BAR decodes, so this read is always safe,
 * and if MEM-enable is clear then an MMIO read genuinely would fault. */

#define kPCIConfigCommand   0x04
#define kPCICmdMemSpace     0x0002

static Boolean       gMemEnabled = false;
static Boolean       gHaveCommand = false;
static unsigned long gPCICommand = 0;

static void CheckMemorySpace(void)
{
    UInt16 cmd = 0;
    gHaveCommand = (ExpMgrConfigReadWord(&gNode, (LogicalAddress)kPCIConfigCommand,
                                         &cmd) == noErr);
    gPCICommand = cmd;
    gMemEnabled = gHaveCommand && (cmd & kPCICmdMemSpace) != 0;
}

/* ---- what the PHY says right now ----------------------------------------- */

static void ReadPhyNow(void)
{
    Str255 line;
    short  r2v, r6v;

    LogText("");
    LogText("=========================================================");
    LogText("  THE PHY'S OWN VIEW, READ NOW");
    LogText("=========================================================");

    FindFireWireNode();
    if (!gHaveNode || gAAPLAddress == 0) {
        SummaryText("No FireWire node / no AAPL,address. PHY not read.");
        return;
    }
    line[0] = 0;
    PStrCat(line, "AAPL,address = 0x"); PStrCatHexN(line, gAAPLAddress, 8);
    Summary(line);

    CheckMemorySpace();
    line[0] = 0;
    PStrCat(line, "PCI command register ");
    if (gHaveCommand) {
        PStrCat(line, "0x"); PStrCatHexN(line, gPCICommand, 4);
        PStrCat(line, gMemEnabled ? "  MEM-space ENABLED" : "  MEM-space OFF");
    } else {
        PStrCat(line, "unreadable");
    }
    Summary(line);

    if (!gMemEnabled) {
        SummaryText("*** THE CONTROLLER'S MEMORY SPACE IS NOT DECODING. ***");
        SummaryText("Not touching MMIO: the read would be a Type 1 bus error. Nothing has");
        SummaryText("claimed this card, which is the signature of an Enabler that failed");
        SummaryText("to LOAD -- check the cfrg container length against the data fork.");
        return;
    }

    gBase = (volatile unsigned char *)gAAPLAddress;
    gOracleOK = OracleCalibrate();
    if (!gOracleOK) {
        SummaryText("Oracle FAILED (GUID/version mismatch). Not touching the PHY.");
        return;
    }
    line[0] = 0;
    PStrCat(line, "oracle OK: OHCI version 0x"); PStrCatHexN(line, gOhciVersion, 8);
    PStrCat(line, gSwap ? "  byte order SWAPPED" : "  byte order native");
    Summary(line);

    r2v = PhyRead(2);
    r6v = PhyRead(6);
    line[0] = 0;
    PStrCat(line, "now: reg2 ");
    if (r2v < 0) PStrCat(line, "<TIMEOUT>"); else { PStrCat(line, "0x"); PStrCatHexN(line, (unsigned long)r2v, 2); }
    PStrCat(line, "   reg6 ");
    if (r6v < 0) PStrCat(line, "<TIMEOUT>"); else { PStrCat(line, "0x"); PStrCatHexN(line, (unsigned long)r6v, 2); }
    if (r6v >= 0) {
        PStrCat(line, "   Max_Legacy_SPD ");
        PStrCatNum(line, (long)((r6v >> 5) & 3));
        PStrCat(line, " (");
        PStrCat(line, SpeedName((unsigned long)((r6v >> 5) & 3)));
        PStrCat(line, ")");
    }
    Summary(line);

    if (gBlocks > 0 && gC[0][kWCalls] > 0 && r2v >= 0 &&
        (unsigned long)r2v != gC[0][kWPhy2]) {
        SummaryText("NOTE: reg2 now differs from reg2 at self-ID time.");
    }
}


/* ---- window -------------------------------------------------------------- */
static void ShowResultWindow(void)
{
    Rect        bounds;
    WindowPtr   win;
    short       screenW, screenH, y, i, page, pages;
    long        deadline;
    EventRecord evt;
    Str255      s;

    pages = (short)((gSummaryCount + kLinesPerPage - 1) / kLinesPerPage);
    if (pages < 1) pages = 1;

    screenW = qd.screenBits.bounds.right  - qd.screenBits.bounds.left;
    screenH = qd.screenBits.bounds.bottom - qd.screenBits.bounds.top;
    bounds.left   = (screenW - 660) / 2; if (bounds.left < 4)  bounds.left = 4;
    bounds.top    = (screenH - 460) / 2; if (bounds.top  < 40) bounds.top  = 40;
    bounds.right  = bounds.left + 660;
    bounds.bottom = bounds.top  + 460;

    win = NewWindow(NULL, &bounds, "\pFireWire S800 Fix Check v8", true, documentProc,
                    (WindowPtr)-1L, false, 0);
    if (win == NULL) return;
    SetPort((GrafPtr)win);
    TextFont(kFontIDGeneva);
    TextSize(9);

    for (page = 0; page < pages; page++) {
        EraseRect(&win->portRect);
        TextFace(bold);
        MoveTo(16, 22);
        DrawString("\pDid the FWIM speed clamp run, and what did the PHY say?");
        TextFace(normal);

        y = 42;
        for (i = page * kLinesPerPage;
             i < gSummaryCount && i < (page + 1) * kLinesPerPage; i++) {
            MoveTo(16, y);
            DrawString(gSummary[i]);
            y += 15;
        }

        y = bounds.bottom - bounds.top - 34;
        s[0] = 0;
        PStrCat(s, "Page ");
        PStrCatNum(s, (long)(page + 1));
        PStrCat(s, " of ");
        PStrCatNum(s, (long)pages);
        PStrCat(s, (page + 1 < pages) ? " - click or key for the next page."
                                      : " - click or key to quit.");
        TextFace(bold); MoveTo(16, y); DrawString(s); TextFace(normal);

        s[0] = 0;
        PStrCat(s, "Log: ");
        PStrCatPStr(s, gLog.where);
        MoveTo(16, y + 16);
        DrawString(s);

        deadline = TickCount() + kLingerTicks;
        while (TickCount() < deadline) {
            if (WaitNextEvent(mDownMask | keyDownMask, &evt, 6, NULL))
                if (evt.what == mouseDown || evt.what == keyDown) break;
        }
    }
    DisposeWindow(win);
}

static void BeepN(short n)
{
    short i;
    for (i = 0; i < n; i++) { SysBeep(12); Delay(18, NULL); }
}




/* ---- entry point --------------------------------------------------------- */

int main(void)
{
    InitGraf(&qd.thePort);
    InitFonts();
    InitWindows();
    InitMenus();
    TEInit();
    InitDialogs(NULL);
    InitCursor();

    LogOpen();
    LogText("FWFixCheck v8 - did the FWIM speed clamp run?");
    LogText("Read-only apart from the PhyControl read requests a PHY read needs.");
    LogText("");

    ScanSystemHeap();
    ReadPhyNow();

    LogClose();
    /* one beep = nothing to report, two = the hook ran, three = the run is void
     * because the old global clamp is still installed. */
    BeepN((short)(gNew > 0 ? 3 : (gBlocks > 0 && gC[0][kWCalls] > 0 ? 2 : 1)));
    ShowResultWindow();
    return 0;
}
