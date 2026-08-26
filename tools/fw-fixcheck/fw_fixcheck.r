/* fw_patchcheck.r — resources for the FWFixCheck diagnostic app.
 *
 * The result window is created programmatically in fw_fixcheck.c (NewWindow), so the
 * only resources needed are the app memory partition and a version stamp.
 */

#include "Processes.r"
#include "Types.r"

/* Application memory partition. Read-only diagnostic; the registry walk holds one
 * node at a time and caps property dumps at 256 bytes, so 640 KB preferred /
 * 512 KB minimum is comfortable headroom for the Toolbox + one window. */
resource 'SIZE' (-1) {
    reserved,
    acceptSuspendResumeEvents,
    reserved,
    canBackground,
    multiFinderAware,
    backgroundAndForeground,
    dontGetFrontClicks,
    ignoreChildDiedEvents,
    is32BitCompatible,
    isHighLevelEventAware,
    onlyLocalHLEvents,
    notStationeryAware,
    dontUseTextEditServices,
    notDisplayManagerAware,
    reserved,
    reserved,
    640 * 1024,    /* preferred */
    512 * 1024     /* minimum   */
};

resource 'vers' (1, "FWFixCheck") {
    0x01,
    0x00,                   /* 1.0 */
    release,
    0x00,
    verUS,
    "1.0",
    "1.0, is the FWServicesLib speed-map patch live in memory?"
};
