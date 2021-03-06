#!/usr/bin/python -tt
#
# Copyright (c) 2011 Intel, Inc.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; version 2 of the License
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc., 59
# Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import os
import shutil
import tempfile

from mic import chroot, msger
from mic.utils import misc, fs_related, errors, cmdln
from mic.conf import configmgr
from mic.plugin import pluginmgr
import mic.imager.loop as loop

from mic.pluginbase import ImagerPlugin
class LoopPlugin(ImagerPlugin):
    name = 'loop'

    @classmethod
    @cmdln.option("--taring-to", dest="taring_to", type='string', default=None, help="Specify the filename for packaging all loop images into a single tarball")
    def do_create(self, subcmd, opts, *args):
        """${cmd_name}: create loop image

        ${cmd_usage}
        ${cmd_option_list}
        """

        if not args:
            raise errors.Usage("More arguments needed")

        if len(args) != 1:
            raise errors.Usage("Extra arguments given")

        creatoropts = configmgr.create
        ksconf = args[0]

        if not os.path.exists(ksconf):
            raise errors.CreatorError("Can't find the file: %s" % ksconf)

        recording_pkgs = []
        if len(creatoropts['record_pkgs']) > 0:
            recording_pkgs = creatoropts['record_pkgs']
        if creatoropts['release'] is not None:
            if 'name' not in recording_pkgs:
                recording_pkgs.append('name')
            ksconf = misc.save_ksconf_file(ksconf, creatoropts['release'])
            name = os.path.splitext(os.path.basename(ksconf))[0]
            creatoropts['outdir'] = "%s/%s/images/%s/" % (creatoropts['outdir'], creatoropts['release'], name)
        configmgr._ksconf = ksconf

        # try to find the pkgmgr
        pkgmgr = None
        for (key, pcls) in pluginmgr.get_plugins('backend').iteritems():
            if key == creatoropts['pkgmgr']:
                pkgmgr = pcls
                break

        if not pkgmgr:
            pkgmgrs = pluginmgr.get_plugins('backend').keys()
            raise errors.CreatorError("Can't find package manager: %s (availables: %s)" % (creatoropts['pkgmgr'], ', '.join(pkgmgrs)))

        creator = loop.LoopImageCreator(creatoropts, pkgmgr, opts.taring_to)

        if len(recording_pkgs) > 0:
            creator._recording_pkgs = recording_pkgs

        if creatoropts['release'] is None:
            if opts.taring_to:
                imagefile = "%s.tar" % os.path.join(creator.destdir, opts.taring_to)
            else:
                imagefile = "%s.img" % os.path.join(creator.destdir, creator.name)
            if os.path.exists(imagefile):
                if msger.ask('The target image: %s already exists, cleanup and continue?' % imagefile):
                    os.unlink(imagefile)
                else:
                    raise errors.Abort('Canceled')

        try:
            creator.check_depend_tools()
            creator.mount(None, creatoropts["cachedir"])
            creator.install()
            creator.configure(creatoropts["repomd"])
            creator.unmount()
            creator.package(creatoropts["outdir"])

            if creatoropts['release'] is not None:
                creator.release_output(ksconf, creatoropts['outdir'], creatoropts['release'])
            creator.print_outimage_info()

        except errors.CreatorError:
            raise
        finally:
            creator.cleanup()

        msger.info("Finished.")
        return 0

    @classmethod
    def do_chroot(cls, target):#chroot.py parse opts&args
        img = target
        imgsize = misc.get_file_size(img) * 1024L * 1024L
        imgtype = misc.get_image_type(img)
        if imgtype == "btrfsimg":
            fstype = "btrfs"
            myDiskMount = fs_related.BtrfsDiskMount
        elif imgtype in ("ext3fsimg", "ext4fsimg"):
            fstype = imgtype[:4]
            myDiskMount = fs_related.ExtDiskMount
        else:
            raise errors.CreatorError("Unsupported filesystem type: %s" % imgtype)

        extmnt = misc.mkdtemp()
        extloop = myDiskMount(fs_related.SparseLoopbackDisk(img, imgsize),
                                                         extmnt,
                                                         fstype,
                                                         4096,
                                                         "%s label" % fstype)
        try:
            extloop.mount()

        except errors.MountError:
            extloop.cleanup()
            shutil.rmtree(extmnt, ignore_errors = True)
            raise

        try:
            chroot.chroot(extmnt, None,  "/bin/env HOME=/root /bin/bash")
        except:
            raise errors.CreatorError("Failed to chroot to %s." %img)
        finally:
            chroot.cleanup_after_chroot("img", extloop, None, extmnt)

    @classmethod
    def do_unpack(cls, srcimg):
        image = os.path.join(tempfile.mkdtemp(dir = "/var/tmp", prefix = "tmp"), "target.img")
        msger.info("Copying file system ...")
        shutil.copyfile(srcimg, image)
        return image
