cmake_minimum_required(VERSION 3.13)
project(FWFixCheck C)

# Configure with the Retro68 PowerPC toolchain, e.g.:
#   cmake -B build \
#     -DCMAKE_TOOLCHAIN_FILE=$HOME/Retro68-build/toolchain/powerpc-apple-macos/cmake/retroppc.toolchain.cmake
#   cmake --build build
#
# READ-ONLY DIAGNOSTIC, a normal PowerPC application (the installed Retro68 PPC
# toolchain is what we have; an INIT is neither needed nor buildable here).
# Double-click it on the FW800 MDD under OS 9: it walks the Name Registry, dumps
# every 1394/OHCI controller with its vendor/device IDs and full property set,
# reports which drivers actually bound, and prints the predicted
# CheckFWIMPersonality outcome for each controller.
#
# The target carries the VERSION in its name (FWFixCheck_v8) so the user can confirm
# at a glance which build is being run. Bump it every iteration, and bump the window
# title in fw_fixcheck.c to match.

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED TRUE)
add_compile_options(-Wno-multichar -Wall)

add_application(FWFixCheck_v8
    fw_fixcheck.c
    fw_fixcheck.r
    TYPE     "APPL"
    CREATOR  "FWFC"
)

# Two extra CFM import libraries beyond InterfaceLib:
#   - NameRegistryLib  -> RegistryEntryIterate{Create,Dispose}, RegistryEntryIterate,
#                         RegistryProperty{Get,GetSize,Iterate*}, RegistryEntryToPathSize,
#                         RegistryCStrEntryToPath, RegistryEntryIDCompare
#   -   -> GetDriverInformation (driver name + DriverDescription + the
#                         RegEntryID of the node the driver bound to)
# (LMGetUnitTableEntryCount is an inline low-memory read; FindFolder/FSp* are InterfaceLib.)
target_link_libraries(FWFixCheck_v8 NameRegistryLib PCILib)

if(TARGET retrocrt)
    add_dependencies(FWFixCheck_v8 retrocrt)
endif()

# Wrap the raw HFS .dsk in an Apple Partition Map so OS 9 will mount it.
set(WRAP_APM ${CMAKE_CURRENT_SOURCE_DIR}/../../client/scripts/wrap-apm.py)
add_custom_command(
    OUTPUT  ${CMAKE_CURRENT_BINARY_DIR}/FWFixCheck_v8.img
    COMMAND /usr/bin/env python3 ${WRAP_APM}
            ${CMAKE_CURRENT_BINARY_DIR}/FWFixCheck_v8.dsk
            ${CMAKE_CURRENT_BINARY_DIR}/FWFixCheck_v8.img
            FWFixCheck_v8
    DEPENDS ${CMAKE_CURRENT_BINARY_DIR}/FWFixCheck_v8.dsk ${WRAP_APM}
    COMMENT "Wrapping FWFixCheck_v8.dsk in Apple Partition Map -> FWFixCheck_v8.img"
    VERBATIM)
add_custom_target(FWFixCheck_v8_disk ALL DEPENDS ${CMAKE_CURRENT_BINARY_DIR}/FWFixCheck_v8.img)
add_dependencies(FWFixCheck_v8_disk FWFixCheck_v8_APPL)
