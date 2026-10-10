# Maintainer: Gyöngyösi Gábor <gabor at gshoots dot hu>
# Contributor: Mark Wagie <mark at manjaro dot org>
# Contributor: Philip Müller <philm[at]manjaro[dot]org>
# Contributor: Thomas Baechler <thomas@archlinux.org>
# Contributor: Sven-Hendrik Haase <svenstaro@gmail.com>
#
# Átírva: Debian 390xx/main patch-sorozat használatára (73 patch).
# A patchek a series.resolved sorrendjében, a kernel/ könyvtárban
# kerülnek alkalmazásra. Manjaro-specifikus kernel-patchek eltávolítva.
# A patchek a PKGBUILD mellett, laposan (nincs debian-patches alkönyvtár).

pkgbase=nvidia-390xx-utils
pkgname=('nvidia-390xx-utils' 'opencl-nvidia-390xx' 'nvidia-390xx-dkms' 'mhwd-nvidia-390xx')
pkgver=390.157
pkgrel=1
arch=('x86_64')
url="https://www.nvidia.com/"
license=('custom')
options=('!strip')
_pkg="NVIDIA-Linux-x86_64-${pkgver}-no-compat32"

# ---- Debian patch lista (a series.resolved-ból, sorrend kötelező) ----
_debian_patches=(
    'cc_version_check-gcc5.patch'
    'bashisms.patch'
    'do-div-cast.patch'
    '0001-backport-error-on-unknown-conftests.patch'
    '0002-backport-error-on-unknown-conftests-uvm-part.patch'
    '0003-backport-set_-memory-pages-_array-_uc-changes-from-5.patch'
    '0004-fix-conftest-includes.patch'
    '0008-backport-nvidia-drm-helper.h-inclusion-from-450.51.patch'
    '0021-backport-acpi_op_remove-changes-from-470.182.03.patch'
    '0022-backport-drm_connector_has_override_edid-changes-fro.patch'
    '0023-backport-vm_area_struct_has_const_vm_flags-changes-f.patch'
    '0024-backport-vm_area_struct_has_const_vm_flags-changes-f.patch'
    '0025-backport-drm_driver_has_dumb_destroy-changes-from-52.patch'
    '0026-backport-get_user_pages-changes-from-418.30.patch'
    '0027-backport-get_user_pages-changes-from-520.56.06.patch'
    '0028-backport-get_user_pages-changes-from-525.53.patch'
    '0029-backport-get_user_pages-changes-from-525.53-uvm-part.patch'
    '0030-backport-get_user_pages-changes-from-535.86.05.patch'
    '0031-backport-asm-page.h-changes-from-470.223.02.patch'
    '0032-backport-drm_gem_prime_handle_to_fd-changes-from-470.patch'
    '0033-refuse-to-load-legacy-module-if-IBT-is-enabled.patch'
    '0034-fix-typos.patch'
    '0038-backport-drm_unlocked_ioctl_flag_present-changes-fro.patch'
    '0040-backport-screen_info-changes-from-470.239.06.patch'
    '0041-backport-CONFIG_MITIGATION_RETPOLINE-changes-from-47.patch'
    '0043-backport-follow_pfn-changes-from-550.90.07.patch'
    '0046-backport-nv_get_kern_phys_address-changes-from-555.4.patch'
    '0047-backport-drm_output_poll_changed-changes-from-535.21.patch'
    '0048-backport-cmd_symlink-changes-from-550.142.patch'
    '0049-backport-uvm-warning-fixes-from-396.18.patch'
    '0049-backport-uvm-warning-fixes-from-415.13.patch'
    '0049-backport-uvm-warning-fixes-from-418.30.patch'
    '0049-backport-warning-fixes-from-430.09.patch'
    '0049-backport-uvm-warning-fixes-from-435.17.patch'
    '0049-backport-uvm-warning-fixes-from-510.39.01.patch'
    '0050-backport-uvm-warning-fixes-from-535.146.02.patch'
    '0051-backport-warning-fixes-from-535.216.01.patch'
    '0052-backport-uvm-warning-fixes-from-560.28.03.patch'
    '0053-fix-more-warnings.patch'
    '0054-fix-more-uvm-warnings.patch'
    '0055-backport-file_operations_fop_unsigned_offset_present.patch'
    '0056-backport-LD_SCRIPT-changes-from-535.230.02.patch'
    '0057-backport-uvm-fixes-from-535.230.02.patch'
    '0060-backport-build_cflags-changes-from-525.85.05.patch'
    '0061-backport-drm_gem_object_vmap_has_map_arg-changes-fro.patch'
    '0063-backport-conftest.sh-comment-changes-from-515.48.07.patch'
    '0063-backport-conftest.sh-comment-changes-from-525.53.patch'
    '0063-backport-conftest.sh-comment-changes-from-545.23.06.patch'
    '0064-backport-drm_driver_has_date-from-570.124.04.patch'
    '0065-backport-ccflags-y-changes-from-570.153.02.patch'
    '0066-backport-nv_timer_delete_sync-changes-from-570.153.0.patch'
    '0067-backport-drm_connector_helper_funcs_mode_valid_has_c.patch'
    '0071-backport-nv_vma_start_write-changes-from-570.169.patch'
    '0074-backport-drm_fb_create_takes_format_info-changes-fro.patch'
    '0075-backport-drm_print.h-changes-from-570.211.01.patch'
    '0076-backport-nv_in_hardirq-changes-from-580.119.02.patch'
    '0077-backport-vma_flags_set_word-changes-from-580.126.09.patch'
    '0078-backport-vma_flags_set_word-changes-from-580.126.09-.patch'
    '0079-backport-dma_map_ops_has_map_phys-changes-from-580.1.patch'
    '0080-backport-for_each_-_plane_in_state-changes-from-580..patch'
    '0081-support-fallback-for-for_each_-_plane_in_state.patch'
    '0082-backport-for_each_-_crtc_in_state-changes-from-580.1.patch'
    '0083-support-fallback-for-for_each_-_crtc_in_state.patch'
    'conftest-verbose.patch'
    'use-kbuild-compiler.patch'
    'use-kbuild-flags.patch'
    'nvidia-use-ARCH.o_binary.patch'
    'nvidia-modeset-use-ARCH.o_binary.patch'
    'include-swiotlb-header-on-arm.patch'
    'ignore_xen_on_arm.patch'
    'arm-outer-sync.patch'
    'nvidia-drm-arm-cflags.patch'
    'armhf-on-arm64-kernel.patch'
    'make-modesetting-default.patch'
    'vma-lock-7.0-plus.patch'
    'fixup-warnings.patch'
    'kernel-7.0-screen_info.patch'
    'kernel-6.18-workqueue-flush.patch'
    'kernel-6.18-prime-fence-flush.patch'
    'kernel-7.2.patch'
    'kernel-7.3-acpi.patch'
)

source=("https://us.download.nvidia.com/XFree86/Linux-x86_64/${pkgver}/${_pkg}.run"
        'mhwd-nvidia'
        'nvidia-390xx-utils.install'
        'nvidia-390xx-utils.sysusers'
        'nvidia-390xx.rules'
        'nvidia-drm-outputclass.conf'
        'systemd-homed-override.conf'
        'systemd-suspend-override.conf'
        '10_nvidia.json'
        'series.resolved'
        "${_debian_patches[@]}"
)

sha256sums=('162317a49aa5a521eb888ec12119bfe5a45cec4e8653efc575a2d04fb05bf581'
            'fa6f1e43b468c7d5b7ad7880cd6be7520f37ebb6e7b8c2c9a08756249754af66'
            '9c18d0b11ef84677983105974bd19b29036d17f496b1f77c58817f97e326d762'
            'd8d1caa5d72c71c6430c2a0d9ce1a674787e9272ccce28b9d5898ca24e60a167'
            '0e54249a7754b668b436f0f7aa7e95fff68edbb12a93dbee4660e09a8c695f84'
            '089d6dc247c9091b320c418b0d91ae6adda65e170934d178cdd4e9bd0785b182'
            'c5aa7b8abe69e72bfdc6b9ee8afbfd350bcc557e894558f2e6e4087fa9aa0dd8'
            '1d053c5078387021338cfc3a732bed61be1a20a549775573788e9134775c8149'
            '9e6f14afaa7523370ad96e6675d3357441ee3985e60405cb3e0ced30b2ddaf76'
            'd4d3d02237af31d236a64b7ef4513350c3133115b66f020f3e6449bfad754851'
            'af5e491da1d10cb6c01e0e46f23939fb22fe412b89dce923eb146c30a79f684e'
            '9605f378ba51feb7c984cd04185fac70a83ff5dd30fbff24ad91404c9312ac82'
            '7c2071c822d927280deafea1fca955c41ca352ce4dd81732063a166a32553f62'
            'c41b6b0a09c02424f9f2b0bfe0cf40f94f7a92deb301ea0c5aa0c3ad55b483e2'
            '7a000183eb473e2cd9ed171b56e1b113e85116517cf25b28dc4a36cc94813933'
            '759c9806349e8dafab51dd9a48adb3369950753e6a10eafc28d51ea6b56a7d38'
            '41cf45477da0df16828720c1e368d8070fb85fac1a5f77d1700dbbd4184a09b5'
            '7302a0713c276288cfd976b42364b51579bfe6596c2af14835688808eb9ad6cf'
            '15d906d84c711e0efa82bf55fd8fc2cd853de38ec637cc163380cd6fcb99e16c'
            '8bae4b495c0d5e36822615d1e83d9ff9ec4fae1e2135ab7afd902f030014d6e5'
            'de183d1f42978c9d98c00d39aff5ae3035a97166f0af6f9cbb00280323465280'
            '7acdd901e6438af1568685b25752c2fb6e200aca7218e45e293ef36ff504eae0'
            'ef7efc5b12f365509aebb99399a0f4eefd2b3c22797e68d66874d140a14d0e14'
            '13e6b65eb95acd5f48d0506bb1b99e98c719dbf7f83ec7b9ce6083ea7e627b64'
            'b3d81eecbfe4fedf55713defd7138812c3ca63c150cd1ded51819bbe49c4977d'
            '080f0e4003d230f776ff9b915957849ca8814db8426d8e7b17c6b830b24bd3ab'
            'a68d86c2d924fa486bc3383fb77f5aa9dd4e05c7162ae3515fcc191e53a3759d'
            '1a9aed41a7c2ed99449a6fe7b3b68d628361fe6b598c45961c57edf1791aa553'
            '6f6428e919dd77da9340da8cb758721f61b7b78c85fdb269995765b23e3bb812'
            '7d6f0914da2a05f4c329fd51ac704fbdb55701de012623d649af24cf417413c5'
            '9711335958d219924f78ec47f35eb86ece768b95b130e12091c37bc0913c131b'
            'ad18693286a66f3aad711ea09750ca96d177d121f825c8c0313ffcdf9507295b'
            'b651c25e044776feed45d66329955f8e71d704832124408aefccac551ec3396d'
            '73e75e0696afb3e3bd9af4e2e6e91bfad4d4dc46a0efd461b77b106159f57bc6'
            '15d4ab89f9f4ae8ea2d3adbe148a924670da3632d1f56ced5fd829467bf779ba'
            '0e2f83ff9a57e2810d5d4d13a8c83d379e81e1903b7b8f9e56162f0107da3101'
            '7ee7df6c22466b37443bc80a7fc78ad65237a44a69faaec3b525fd2ed4f15ab1'
            'db6829656d7f538701c5b7409bbaac57ef28eb9d11a664cb93cab48a7161a9ea'
            '1d1e81b4da1fa30f311d7553e62247bb5c5b39f2f2d215112dd3b4f98dd26856'
            '81bf2bfa205edc44f25dc36ae987966bde7cc0dfe5e01377d8e068ac4a539a6c'
            '26d5b046281c55d603d6b59704e8efae308bd6791a5b8ab95ea86cdfc442b529'
            'ee00fbd88271edc10d24c07ee1e9de51003f155855fbd8a160a8d311f1af88bd'
            'd2ca03798df22471f3193d45c671ffa29f62ef1eb3b39c2036437f9aab0fe5b3'
            '21eb2cb88867c454dce8f8b4fb09b0f624f3731159c4274762c2ca2520d18b9f'
            '09a91e7cfd3c239701eeabe8be4c09dfe71a16118889b26f757be8176d9d30b3'
            '30ee488a0101ad78e8dcff5f6dc7e2198f25c505d461aa4f20731096e25913e8'
            '8a4a11ed48b9abb8bae80366a47c3890706cbe315dc55dd91f07f59f136ddb44'
            '47780dcb13ffc94a67fced72bbab25009434224dfabd7f5b850dd7f1858d28be'
            '5bd671a6bed4578f40a6940ad872cb04da33405a80080e452f8ee58045299cbc'
            '72047699802ff61b3a990a227cde816c45f7f7eb10f10a324ab376409cfd586f'
            '8bd6f7efc235162968e0a464be2a576c71be057276e0340725cab18a0a23d518'
            '1c902c7b438125f46f971dd3b4dece7f830863c0317d65660b05072839b17135'
            '353f208ab2f01b4093d51cf93063ed63918bd18b5f7d116432b60e266e69e3a3'
            'd7b562536b67ac55fb770746b93940ff5047fb867a2a45808a374324c3c2cf53'
            'd0b08befc0ff5d305f09986313791e027ac9e0b1e22b99576a7921295f3131ee'
            '113eaff7e9718ccf496c747bab3b2e66828568c09cd9fe4452a7980cde9d0d4a'
            '96531a70c6274a20cd9df59aba5037d022526a562d2057b7034e56a8cb0f321f'
            'e3750d234a2c897ac3ba00ab20996cfe0653cc09c77d7a9a5c46bec017bb83e0'
            '2de7e6077e032ebd57244c5b65f80e30bb343ca44dd1c7dcd4b0a36b95738634'
            '116bf0805ac4f381115ec539d0e12165971b8031a91a5b6fe615273e1ef6e9a4'
            'a0737efa9ba1c6c4a6596d5566422997b7d61fd9e94a8d1ffe85dd1baff4ccb0'
            '1c1e09d036b01dfb327e59e231baa569f1484f3b832401a3c9a6687a5f45b35c'
            '3e1735c917897b1298220d5e3dcf1148f297a1ad54748dcce6a87a500b154cea'
            '02508386781db60d4724889075c3fb327a46177401dcfd9792216ec7c2b97eb6'
            'e909d73ccdc1e329210c983d84d79efbdd3dda4706e4c3fdc1c5f33340778d71'
            'ae9d4d65fa9d6d0ce659be0e6b1451b21446c56d2d6a242b0af4a9e7d73fc597'
            '044ed3ac699fdc52886ea43f92e5bcd137b540484edd3e167caa5f52029aacfb'
            'e67c92021d36baa805fbe1282000d418bfd8df370a3536872b42c6af26e2e560'
            'a1c8d8e39cb00053db1eb7a53c3d24797b2a8871190b3de2a52b3636032a825c'
            '1f9cab8055d0a4cfa8734c309061b83e4143b5ca867e9ec6e60e710802b6d88e'
            '213822f133280145cb9676fa34d47c7db80e54efb8f631b7267b882ccb9205d2'
            'b337e68a52240ba66199fb891d0d1bcf3712d64b00603c25704fe7b6c4792c6c'
            '88e4bac2d74847802b8924a9164a7d14ad94b46a92a3f1853acf15590ee36c11'
            'd5ff015cd9bc4362936f137b7978939c23bb618d985376b17fe84f3ff61f6b06'
            'fbbc34b2aa49a984209ed563be0d961fcab1698ee27a5d1837da402a652c9c6b'
            'a124f07b3b5fe3d2394c4136e84be972ca5d351cce1ea3e717323269e7bb1a86'
            '11babb178b743f46011e8848496044c9c56ce35050290951bfe508f15085ef56'
            '611c9700ba196da4fa7c88067292ab0014c9f23237f16c068065aeecba83fb3a'
            '6fafef5d0e5953b5654ad05bdfa676306eb96d2fa5f21399e3e5cc51e8207d6e'
            '7df0535acebbecf6d3c478162a119eb8faac0103831dddba4926bf28f9997306'
            '93ec4257b95d61b9fef6740838483ab43d55d649032bf263752cc6811d0c99ab'
            '6ab44a4905e69e2d39470c328ed734a9aa610c7b25bad00bde3eab14b1d87c09'
            'fa2348ed0947bacfc96c0a57d229b11ffd0f945032e182ad0d627a7db2b4acbc'
            '588feb34eac6458680702efb27f466de385434443e21930b2b20eee039e8cfd4'
            '4e6a671112090e64aaa8cc715aeb3b93ba15a8c0cdf3dae0763496fbb208a9a0'
            '586839a010bfb82cd15813a37c56800fcb827cb27b705049579cfeb3e9040079'
            'e35b11f543cddbdb211a6042090c99c5bb9642c61542e52127773f536e7262b6'
            '9e39a4e5b65834c3b223125db4a5fb07901ea6200a2c5f2f1475acbfbd4ddf27'
            'a9eea9b7ecd655f998a2801015dc9c093df47022c634b346980b02b3fa2855d2'
            '63c992a601544d98434c9bf9b567129dbfb43c227e7f82ba69218201f7e3916d'
            '919b2b04357ce50a461d1a407bf7c9c58fad632a8c8285754b550b6e177575a5')

create_links() {
    find "$pkgdir" -type f -name '*.so*' ! -path '*xorg/*' -print0 | while read -d $'\0' _lib; do
        _soname=$(dirname "${_lib}")/$(readelf -d "${_lib}" | grep -Po 'SONAME.*: \[\K[^]]*' || true)
        _base=$(echo ${_soname} | sed -r 's/(.*)\.so.*/\1.so/')
        [[ -e "${_soname}" ]] || ln -s $(basename "${_lib}") "${_soname}"
        [[ -e "${_base}" ]] || ln -s $(basename "${_soname}") "${_base}"
    done
}

prepare() {
    rm -rf "${_pkg}"
    sh "${_pkg}.run" --extract-only

    cd "${_pkg}"

    bsdtar -xf nvidia-persistenced-init.tar.bz2
    sed -i 's/__NV_VK_ICD__/libGLX_nvidia.so.0/' nvidia_icd.json.template

    cd kernel

    # -----------------------------------------------------------------------
    # 1. Debian patch-sorozat alkalmazása
    # -----------------------------------------------------------------------
    echo ">>> Debian patch-sorozat alkalmazása (kernel/ könyvtárban)..."

    if [ ! -f "${srcdir}/series.resolved" ]; then
        echo "!!! HIBA: hiányzik a series.resolved a PKGBUILD mellől"
        exit 1
    fi

    local _n=0
    local _total
    _total=$(grep -cve '^[[:space:]]*$' "${srcdir}/series.resolved")

    while IFS= read -r _patch || [ -n "$_patch" ]; do
        _patch="${_patch%$'\r'}"
        [ -z "${_patch//[[:space:]]/}" ] && continue
        _n=$((_n + 1))
        _patchfile="${srcdir}/${_patch}"

        if [ ! -f "$_patchfile" ]; then
            echo "!!! HIBA: hiányzó patch: $_patchfile"
            exit 1
        fi

        printf '[%3d/%d] %s\n' "$_n" "$_total" "$_patch"
        patch -Np1 --forward --no-backup-if-mismatch < "$_patchfile" \
            || { echo "!!! PATCH FAILED: $_patch"; exit 1; }
    done < "${srcdir}/series.resolved"

    echo ">>> Mind a $_n patch sikeresen alkalmazva."

    # -----------------------------------------------------------------------
    # 2. Debian build-stamp blob-előkészítés — 390-nél KÉT blob van.
    #    Az eredeti .o_binary-ket átnevezzük arch-specifikusra, hogy a
    #    use-ARCH.o_binary patchek receptjei garantáltan lefussanak és
    #    létrejöjjenek a .cmd fájlok (modpost ne hasaljon el).
    # -----------------------------------------------------------------------
    if [ ! -f nvidia/nv-kernel.o_binary ]; then
        echo "!!! HIBA: hiányzik kernel/nvidia/nv-kernel.o_binary"
        exit 1
    fi
    mv -f nvidia/nv-kernel.o_binary nvidia/nv-kernel-amd64.o_binary
    echo ">>> nvidia/nv-kernel.o_binary → nvidia/nv-kernel-amd64.o_binary"

    if [ ! -f nvidia-modeset/nv-modeset-kernel.o_binary ]; then
        echo "!!! HIBA: hiányzik kernel/nvidia-modeset/nv-modeset-kernel.o_binary"
        exit 1
    fi
    mv -f nvidia-modeset/nv-modeset-kernel.o_binary nvidia-modeset/nv-modeset-kernel-amd64.o_binary
    echo ">>> nvidia-modeset/nv-modeset-kernel.o_binary → nvidia-modeset/nv-modeset-kernel-amd64.o_binary"

    # -----------------------------------------------------------------------
    # 3. DKMS workaround: KERNELRELEASE semlegesítése a top-level make híváskor.
    # -----------------------------------------------------------------------
    {
        cat <<'EOF_HEADER'
# --- DKMS workaround: KERNELRELEASE semlegesítése a top-level híváskor ---
ifeq ($(M),)
  override KERNELRELEASE :=
endif
# --- end DKMS workaround ---
EOF_HEADER
        cat Makefile
    } > Makefile.new
    mv Makefile.new Makefile

    echo ">>> DKMS workaround hozzáadva a kernel/Makefile tetejére."

    # -----------------------------------------------------------------------
    # 4. DKMS dkms.conf előkészítése — 390-nél 4 modul.
    # -----------------------------------------------------------------------
    sed -i "s/__VERSION_STRING/${pkgver}/" dkms.conf
    sed -i 's/__JOBS/`nproc`/' dkms.conf
    sed -i 's/__DKMS_MODULES//' dkms.conf
    sed -i '$iBUILT_MODULE_NAME[0]="nvidia"\
DEST_MODULE_LOCATION[0]="/kernel/drivers/video"\
BUILT_MODULE_NAME[1]="nvidia-uvm"\
DEST_MODULE_LOCATION[1]="/kernel/drivers/video"\
BUILT_MODULE_NAME[2]="nvidia-modeset"\
DEST_MODULE_LOCATION[2]="/kernel/drivers/video"\
BUILT_MODULE_NAME[3]="nvidia-drm"\
DEST_MODULE_LOCATION[3]="/kernel/drivers/video"' dkms.conf

    sed -i 's/NV_EXCLUDE_BUILD_MODULES/IGNORE_PREEMPT_RT_PRESENCE=1 NV_EXCLUDE_BUILD_MODULES/' dkms.conf

    cd ..
}

package_opencl-nvidia-390xx() {
    pkgdesc="OpenCL implemention for NVIDIA"
    depends=('zlib')
    optdepends=('opencl-headers: headers necessary for OpenCL development')
    provides=("opencl-nvidia=${pkgver}" 'opencl-driver')
    conflicts=('opencl-nvidia')

    cd "${_pkg}"

    install -Dm644 nvidia.icd "${pkgdir}/etc/OpenCL/vendors/nvidia.icd"
    install -Dm755 "libnvidia-compiler.so.${pkgver}" "${pkgdir}/usr/lib/libnvidia-compiler.so.${pkgver}"
    install -Dm755 "libnvidia-opencl.so.${pkgver}" "${pkgdir}/usr/lib/libnvidia-opencl.so.${pkgver}"

    create_links

    mkdir -p "${pkgdir}/usr/share/licenses"
    ln -s nvidia "${pkgdir}/usr/share/licenses/opencl-nvidia"
}

package_nvidia-390xx-dkms() {
    pkgdesc="NVIDIA driver sources for linux, 390xx legacy branch"
    depends=('dkms' "nvidia-390xx-utils=${pkgver}" 'libglvnd')
    provides=('NVIDIA-MODULE' "nvidia-dkms=${pkgver}")
    conflicts=('nvidia-dkms')

    cd "${_pkg}"

    install -dm 755 "${pkgdir}"/usr/src
    cp -dr --no-preserve='ownership' kernel "${pkgdir}/usr/src/nvidia-${pkgver}"

    install -Dt "${pkgdir}/usr/share/licenses/${pkgname}" -m644 "${srcdir}/${_pkg}/LICENSE"
}

package_nvidia-390xx-utils() {
    pkgdesc="NVIDIA drivers utilities"
    depends=('xorg-server' 'libglvnd' 'egl-wayland')
    optdepends=("nvidia-390xx-settings=${pkgver}: configuration tool"
                'xorg-server-devel: nvidia-xconfig'
                'opencl-nvidia-390xx: OpenCL support')
    conflicts=('nvidia-libgl' 'nvidia-utils' 'nvidia-390xx-libgl')
    provides=('vulkan-driver' 'opengl-driver' 'nvidia-libgl' "nvidia-utils=${pkgver}" 'nvidia-390xx-libgl')
    replaces=('nvidia-390xx-libgl')
    install="${pkgname}.install"

    cd "${_pkg}"

    # X driver
    install -Dm755 nvidia_drv.so "${pkgdir}/usr/lib/xorg/modules/drivers/nvidia_drv.so"

    # GLX extension module for X
    install -Dm755 "libglx.so.${pkgver}" "${pkgdir}/usr/lib/nvidia/xorg/libglx.so.${pkgver}"
    ln -s "libglx.so.${pkgver}" "${pkgdir}/usr/lib/nvidia/xorg/libglx.so.1"
    ln -s "libglx.so.${pkgver}" "${pkgdir}/usr/lib/nvidia/xorg/libglx.so"

    install -Dm755 "libGLX_nvidia.so.${pkgver}" "${pkgdir}/usr/lib/libGLX_nvidia.so.${pkgver}"

    # OpenGL libraries (GLVND)
    install -Dm755 "libEGL_nvidia.so.${pkgver}"          "${pkgdir}/usr/lib/libEGL_nvidia.so.${pkgver}"
    install -Dm755 "libGLESv1_CM_nvidia.so.${pkgver}"    "${pkgdir}/usr/lib/libGLESv1_CM_nvidia.so.${pkgver}"
    install -Dm755 "libGLESv2_nvidia.so.${pkgver}"       "${pkgdir}/usr/lib/libGLESv2_nvidia.so.${pkgver}"
    install -Dm644 "${srcdir}/10_nvidia.json"            "${pkgdir}/usr/share/glvnd/egl_vendor.d/10_nvidia.json"

    # OpenGL core library
    install -Dm755 "libnvidia-glcore.so.${pkgver}"  "${pkgdir}/usr/lib/libnvidia-glcore.so.${pkgver}"
    install -Dm755 "libnvidia-eglcore.so.${pkgver}" "${pkgdir}/usr/lib/libnvidia-eglcore.so.${pkgver}"
    install -Dm755 "libnvidia-glsi.so.${pkgver}"    "${pkgdir}/usr/lib/libnvidia-glsi.so.${pkgver}"

    # misc
    install -Dm755 "libnvidia-ifr.so.${pkgver}"    "${pkgdir}/usr/lib/libnvidia-ifr.so.${pkgver}"
    install -Dm755 "libnvidia-fbc.so.${pkgver}"    "${pkgdir}/usr/lib/libnvidia-fbc.so.${pkgver}"
    install -Dm755 "libnvidia-encode.so.${pkgver}" "${pkgdir}/usr/lib/libnvidia-encode.so.${pkgver}"
    install -Dm755 "libnvidia-cfg.so.${pkgver}"    "${pkgdir}/usr/lib/libnvidia-cfg.so.${pkgver}"
    install -Dm755 "libnvidia-ml.so.${pkgver}"     "${pkgdir}/usr/lib/libnvidia-ml.so.${pkgver}"

    # Vulkan ICD
    install -Dm644 "nvidia_icd.json.template" "${pkgdir}/usr/share/vulkan/icd.d/nvidia_icd.json"

    # VDPAU
    install -Dm755 "libvdpau_nvidia.so.${pkgver}" "${pkgdir}/usr/lib/vdpau/libvdpau_nvidia.so.${pkgver}"

    # nvidia-tls library
    install -Dm755 "tls/libnvidia-tls.so.${pkgver}" "${pkgdir}/usr/lib/libnvidia-tls.so.${pkgver}"

    # CUDA
    install -Dm755 "libcuda.so.${pkgver}"    "${pkgdir}/usr/lib/libcuda.so.${pkgver}"
    install -Dm755 "libnvcuvid.so.${pkgver}" "${pkgdir}/usr/lib/libnvcuvid.so.${pkgver}"

    # PTX JIT Compiler
    install -Dm755 "libnvidia-ptxjitcompiler.so.${pkgver}" "${pkgdir}/usr/lib/libnvidia-ptxjitcompiler.so.${pkgver}"

    # Fat binary loader
    install -Dm755 "libnvidia-fatbinaryloader.so.${pkgver}" "${pkgdir}/usr/lib/libnvidia-fatbinaryloader.so.${pkgver}"

    # DEBUG
    install -Dm755 nvidia-debugdump "${pkgdir}/usr/bin/nvidia-debugdump"

    # nvidia-xconfig
    install -Dm755 nvidia-xconfig "${pkgdir}/usr/bin/nvidia-xconfig"
    install -Dm644 nvidia-xconfig.1.gz "${pkgdir}/usr/share/man/man1/nvidia-xconfig.1.gz"

    # nvidia-bug-report
    install -Dm755 nvidia-bug-report.sh "${pkgdir}/usr/bin/nvidia-bug-report.sh"

    # nvidia-smi
    install -Dm755 nvidia-smi "${pkgdir}/usr/bin/nvidia-smi"
    install -Dm644 nvidia-smi.1.gz "${pkgdir}/usr/share/man/man1/nvidia-smi.1.gz"

    # nvidia-cuda-mps
    install -Dm755 nvidia-cuda-mps-server "${pkgdir}/usr/bin/nvidia-cuda-mps-server"
    install -Dm755 nvidia-cuda-mps-control "${pkgdir}/usr/bin/nvidia-cuda-mps-control"
    install -Dm644 nvidia-cuda-mps-control.1.gz "${pkgdir}/usr/share/man/man1/nvidia-cuda-mps-control.1.gz"

    # nvidia-modprobe
    install -Dm4755 nvidia-modprobe "${pkgdir}/usr/bin/nvidia-modprobe"
    install -Dm644 nvidia-modprobe.1.gz "${pkgdir}/usr/share/man/man1/nvidia-modprobe.1.gz"

    # nvidia-persistenced
    install -Dm755 nvidia-persistenced "${pkgdir}/usr/bin/nvidia-persistenced"
    install -Dm644 nvidia-persistenced.1.gz "${pkgdir}/usr/share/man/man1/nvidia-persistenced.1.gz"
    install -Dm644 nvidia-persistenced-init/systemd/nvidia-persistenced.service.template \
        "${pkgdir}/usr/lib/systemd/system/nvidia-persistenced.service"
    sed -i 's/__USER__/nvidia-persistenced/' "${pkgdir}/usr/lib/systemd/system/nvidia-persistenced.service"

    # application profiles
    install -Dm644 nvidia-application-profiles-${pkgver}-rc \
        "${pkgdir}/usr/share/nvidia/nvidia-application-profiles-${pkgver}-rc"
    install -Dm644 nvidia-application-profiles-${pkgver}-key-documentation \
        "${pkgdir}/usr/share/nvidia/nvidia-application-profiles-${pkgver}-key-documentation"

    install -Dm644 LICENSE "${pkgdir}/usr/share/licenses/nvidia/LICENSE"
    ln -s nvidia "${pkgdir}/usr/share/licenses/nvidia-utils"
    install -Dm644 README.txt "${pkgdir}/usr/share/doc/nvidia/README"
    install -Dm644 NVIDIA_Changelog "${pkgdir}/usr/share/doc/nvidia/NVIDIA_Changelog"
    cp -r html "${pkgdir}/usr/share/doc/nvidia/"
    ln -s nvidia "${pkgdir}/usr/share/doc/nvidia-utils"

    # systemd overrides (Systemd 256)
    install -Dm644 "${srcdir}/systemd-homed-override.conf" \
        "${pkgdir}/usr/lib/systemd/system/systemd-homed.service.d/10-nvidia-no-freeze-session.conf"
    install -Dm644 "${srcdir}/systemd-suspend-override.conf" \
        "${pkgdir}/usr/lib/systemd/system/systemd-suspend.service.d/10-nvidia-no-freeze-session.conf"
    install -Dm644 "${srcdir}/systemd-suspend-override.conf" \
        "${pkgdir}/usr/lib/systemd/system/systemd-suspend-then-hibernate.service.d/10-nvidia-no-freeze-session.conf"
    install -Dm644 "${srcdir}/systemd-suspend-override.conf" \
        "${pkgdir}/usr/lib/systemd/system/systemd-hibernate.service.d/10-nvidia-no-freeze-session.conf"
    install -Dm644 "${srcdir}/systemd-suspend-override.conf" \
        "${pkgdir}/usr/lib/systemd/system/systemd-hybrid-sleep.service.d/10-nvidia-no-freeze-session.conf"

    # Xorg outputclass (Manjaro-specifikus)
    install -Dm644 "${srcdir}/nvidia-drm-outputclass.conf" \
        "${pkgdir}/usr/share/X11/xorg.conf.d/10-nvidia-drm-outputclass.conf"

    # udev rules
    install -Dm644 "${srcdir}/nvidia-390xx.rules" \
        "${pkgdir}/usr/lib/udev/rules.d/60-nvidia-390xx.rules"

    # sysusers
    install -Dm644 "${srcdir}/nvidia-390xx-utils.sysusers" \
        "${pkgdir}/usr/lib/sysusers.d/${pkgname}.conf"

    echo "blacklist nouveau" | install -Dm644 /dev/stdin "${pkgdir}/usr/lib/modprobe.d/${pkgname}.conf"
    echo "nvidia-uvm"        | install -Dm644 /dev/stdin "${pkgdir}/usr/lib/modules-load.d/${pkgname}.conf"

    create_links
}

package_mhwd-nvidia-390xx() {
    pkgdesc="MHWD module-ids for nvidia ${pkgver}"
    arch=('any')
    depends=('mhwd')

    install -d -m755 "${pkgdir}/var/lib/mhwd/ids/pci/"

    sh -e ${srcdir}/mhwd-nvidia \
        ${srcdir}/${_pkg}/README.txt \
        ${srcdir}/${_pkg}/kernel/nvidia/nv-kernel-amd64.o_binary \
        > ${pkgdir}/var/lib/mhwd/ids/pci/nvidia-390xx.ids

    sed -i 's/1b81 1b84/1b81 1b82 1b84/g' ${pkgdir}/var/lib/mhwd/ids/pci/nvidia-390xx.ids
}
