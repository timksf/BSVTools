#!/usr/bin/env python3

import sys
import subprocess
import argparse
import os
import shutil
import glob
import subprocess
import re
from shutil import which

vendor = "esa.informatik.tu-darmstadt.de"
createNewProject = """
ipx::infer_core -vendor {vendor} -name {projectname} -library user -taxonomy /UserIP -files {directory}/src/{topModule}.v -root_dir {directory}
ipx::edit_ip_in_project -upgrade true -name edit_ip_project -directory {tmpdir} {directory}/component.xml
ipx::current_core {directory}/component.xml
set_property top {topModule} [current_fileset]
set_property -quiet interface_mode monitor [ipx::get_bus_interfaces *MON* -of_objects [ipx::current_core]]
add_files {directory}/src
update_compile_order -fileset sources_1
set_property name {projectname} [ipx::current_core]
set_property display_name {projectname} [ipx::current_core]
set_property description {projectname} [ipx::current_core]
set_property core_revision 1 [ipx::current_core]
set_property AUTO_FAMILY_SUPPORT_LEVEL level_1 [ipx::current_core]
foreach f {{ {includes} }} {{
    set_property is_global_include true [get_files $f]
}}
update_compile_order -fileset sources_1
update_compile_order -fileset sim_1
ipx::merge_project_changes files [ipx::current_core]
ipx::merge_project_changes ports [ipx::current_core]
puts "USED FILES"
foreach f [ipx::get_files -of_objects [ipx::get_file_groups *synthesis*]] {{
    set n [get_property NAME $f]
    puts "USED FILE:$n"
}}
puts "END USED FILES"
puts "Additional Parameters"
{additional_parameters}
puts "End Additional Parameters"
ipx::create_xgui_files [ipx::current_core]
ipx::update_checksums [ipx::current_core]
ipx::save_core [ipx::current_core]
close_project -delete
puts "VIVADO FINISHED SUCCESSFULLY"
"""

def copyBSVVerilog(src, dest, exclude="", includevivado=True):
    for filename in glob.glob(os.path.join(src, 'Verilog', '*.v')):
        if not os.path.basename(filename) in exclude:
            addLicenseHeader(shutil.copy(filename, dest))
    if includevivado:
        for filename in glob.glob(os.path.join(src, 'Verilog.Vivado', '*.v')):
            if not os.path.basename(filename) in exclude:
                addLicenseHeader(shutil.copy(filename, dest))


def addLicenseHeader(file):
    header = """/*
    SPDX-License-Identifier: BSD-3-Clause

    SPDX-FileCopyrightText: Copyright (c) 2020 Bluespec, Inc. All rights reserved.
*/
"""
    f = open(file, 'r').read()
    open(file, 'w').write(header + f)

def copyNGC(src, dest, exclude):
    for path in src:
        if path.endswith('.ngc'):
            if not os.path.basename(path) in exclude:
                    shutil.copy(path, dest)

def copyVerilog(src, dest, exclude):
    for path in src:
        if path.endswith('.v') or path.endswith('.vhd') or path.endswith('.h') or path.endswith('.sv'):
            if not os.path.basename(path) in exclude:
                    flattenVerilogIncludes(path, dest)
        else:
            verilogfiles = glob.glob(os.path.join(path, '*.v'))
            sysverilogfiles = glob.glob(os.path.join(path, '*.sv'))
            vhdlfiles = glob.glob(os.path.join(path, '*.vhd'))
            headerfiles = glob.glob(os.path.join(path, '*.h'))
            allfiles = verilogfiles + vhdlfiles + headerfiles + sysverilogfiles
            for filename in allfiles:
                if not os.path.basename(filename) in exclude:
                    flattenVerilogIncludes(filename, dest)

def wslpath(path):
    """converts the linux path to the corresponding windows path"""
    process = subprocess.run(["wslpath", "-m", path], capture_output=True)
    wpath = process.stdout.decode().replace('\n', '') # wslpath ends its output with \n
    if process.returncode != 0:
        print("Could not convert {path} to windows path".format(path=path))
        return path # something went wrong, maybe the path did not exist?
    return wpath


def executeVivado(tcl, vendor, projectname, ippath, tmpdir, topModule, additional, includes):
    vivadoCmd = "vivado"
    # check whether we are running in WSL
    if os.getenv("WSL_DISTRO_NAME") is not None:
        print("Detected that we are running in WSL")
        vivadoCmd = "cmd.exe /c vivado.bat" # run vivado.bat through cmd.exe
        ippath = wslpath(ippath) # convert linux paths to windows paths
        tmpdir = wslpath(tmpdir)
        includes = [wslpath(include) for include in includes]

    if which("vivado") is None:
        print("Could not find \"vivado\". Make sure Vivado is in the path.")
        sys.exit(1)
    with open('temp.tcl', "w+") as f:
        f.write(tcl.format(vendor=vendor,directory=ippath,projectname=projectname,tmpdir=tmpdir,topModule=topModule, additional_parameters=additional, includes=" ".join(includes)))
    t = subprocess.Popen(vivadoCmd + " -mode batch -source temp.tcl -nojournal -nolog", shell=True, stdout=subprocess.PIPE).stdout.read()
    os.remove('temp.tcl')
    usedfiles = []
    s = t.decode()
    success = re.search(r"VIVADO FINISHED SUCCESSFULLY", s)
    if success:
        print("Vivado finished successfully.")
    else:
        print(s)
        print("Vivado failed. Check above log for errors.")
        sys.exit(1)

    for l in t.splitlines():
        if l.startswith(b"USED FILE:"):
            lt = l.split(b':')
            usedfiles.append(lt[1].decode("utf-8") )
    return usedfiles

def removeUnused(used, srcpath):
    for filename in os.listdir(srcpath):
        fullname = os.path.join(srcpath, filename)
        if not fullname in used:
            os.unlink(fullname)

def flattenVerilogIncludes(src, dst):
    with open(src, "r") as src_file:
        dstFilename = dst + '/' + os.path.basename(src)
        with open(dstFilename, "w") as dst_file:
            for l in src_file:
                m = re.search("^\s*`include \"(.*)\"", l)
                if m:
                    dst_file.write("`include \"" + os.path.basename(m.group(1)) + "\"")
                else:
                    dst_file.write(l)

def parseConstraints(s):
    constraints = []
    for c in s:
        if c:
            try:
                p, t = c.split(',')
            except:
                print("Constraints have to be provided in the format PATH,LOAD_PRIORITY")
                sys.exit()
            load_times = ["LATE", "NORMAL", "EARLY"]
            if not t in load_times:
                print("Load priority has to be one of {}".format(load_times))
                sys.exit()
            constraints.append({"path":p, "priority":t})
    return constraints

def processConstraints(s, p):
    additional = ""
    if s:
        os.makedirs(p)
        for t in s:
            cp = t["path"]
            ct = t["priority"]
            filename = os.path.basename(cp)
            shutil.copyfile(cp, p+'/'+filename)
            additional += "add_files -fileset constrs_1 -norecurse {}/{}\n".format(p, filename)
            additional += "set_property PROCESSING_ORDER {} [get_files {}/{}]\n".format(ct, p, filename)
        additional += "ipx::merge_project_changes files [ipx::current_core]"
    return additional


def mkVivado(cli):
    ippath = "{cwd}/ip/{projectname}".format(projectname=cli.projectname,cwd=os.getcwd())
    srcpath = "{ippath}/src".format(ippath=ippath)
    inclpath = "{ippath}/src".format(ippath=ippath)
    constraintpath = "{ippath}/constraints".format(ippath=ippath)
    constraints = parseConstraints(cli.constraints)
    includefiles = []
    for path in cli.includes:
        if path.endswith('.v') or path.endswith('.h'):
            includefiles.append(path)
        else:
            for filename in glob.glob(os.path.join(path, '*.v')):
                includefiles.append(filename)

    includes = ['{ippath}/src/{file}'.format(ippath=ippath, file=os.path.basename(x)) for x in includefiles]
    tmpdir = "{cwd}/tmp".format(cwd=os.getcwd())
    print("Creating project with files in {}".format(cli.verilog_dir[0]))
    for path in cli.verilog_dir:
        if not os.path.exists(path):
            print("Cant find {}".format(path))
            return
    if not os.path.exists(srcpath):
        os.makedirs(srcpath)
    else:
        print("{} already exists.".format(srcpath))
        return

    if not os.path.exists(tmpdir):
        os.makedirs(tmpdir)

    copyVerilog(cli.verilog_dir, srcpath, cli.exclude)
    if cli.includes:
        copyVerilog(cli.includes, inclpath, cli.exclude)
    copyNGC(cli.verilog_dir, srcpath, cli.exclude)
    copyBSVVerilog(cli.bluespec_dir, srcpath)
    additional = "\n".join(cli.additional)
    additional += '\n'

    additional += processConstraints(constraints, constraintpath)

    used = executeVivado(createNewProject, cli.vendor, cli.projectname, ippath, tmpdir, cli.topModule, additional, includes)
    used_fullpath = []
    usedNGC = []
    for usedFile in used:
        base_file, ext = os.path.splitext(usedFile)
        used_fullpath.append("{}/src/{}".format(ippath, os.path.basename(usedFile)))
        ngcFile = base_file + ".ngc"
        if os.path.exists(ngcFile):
            usedNGC += [base_file + ".ngc"]

    used = used_fullpath + usedNGC
    removeUnused(used, srcpath)


class mkYosys():

    valid_synth_targets = ["ecp5", "ice40"]
    # map from synth target to pin constraint arg for nextpnr
    constraintsids = { "ecp5": "lpf", "ice40": "pcf"}
    # map from synth target to nextpnr output option and file ending
    pnr_outfiles = { "ecp5" : ("textcfg", "txt"), "ice40": ("asc", "asc") }
    # map from synth target to bitstream packing command and file ending
    bitstream_packing = { "ecp5" : ("ecppack", "bit"), "ice40": ("icepack", "bin")}

    valid_render_exts = ["pdf", "png"]

    def __init__(self, cli):

        synth = False

        if cli.synth_and_target != "":
            if cli.synth_and_target not in mkYosys.valid_synth_targets:
                print(f"Synth target has to be one of: {mkYosys.valid_synth_targets}")
                return  
            synth = True
            
        synthtarget = cli.synth_and_target
        synthpath = os.path.join(os.getcwd(), "synth", cli.projectname)
        srcpath = os.path.join(synthpath, "src")
        reportspath = os.path.join(synthpath, "reports")

        # constraints command interpreted as pin constraint file
        if len(cli.constraints) != 1:
            print(f"Provide one pin constraint file for synthesis")
            return

        if synth: # constraint files only matter when synthesis is enabled
            constraintsid = mkYosys.constraintsids[synthtarget]
            constraints = cli.constraints[0]
            constraints_file = os.path.join(cli.base_dir, constraints)
            if constraints != "" and not os.path.isfile(constraints_file):
                print(f"Cannot find constraints file {constraints_file}")
                return
    
        # create output directory
        if not os.path.exists(srcpath):
            os.makedirs(srcpath)
        else:
            print(f"{srcpath} already exists")
            return

        # add explicitly passed verilog files or if directory passed, all verilog files in dir
        includefiles = []
        for path in cli.includes:
            if path.endswith('.v'):
                includefiles.append(path)
            else:
                for filename in glob.glob(os.path.join(path, '*.v')):
                    includefiles.append(filename)

        # copy over relevant verilog files
        copyVerilog(cli.verilog_dir, srcpath, cli.exclude)
        # copy explicitly passed verilog files from some include directory
        if cli.includes:
            copyVerilog(cli.includes, srcpath, cli.exclude)

        # yosys does not work with these files (issue #2613)
        # main.v is not needed for synthesis
        yosys_excludes = """
            InoutConnect.v
            ProbeHook.v
            ConstrainedRandom.v
            BRAM1BELoad.v BRAM1Load.v
            BRAM2BELoad.v BRAM2Load.v
            RegFileLoad.v
            main.v
        """
        print(f"Not including following sources due to incompatibility with yosys: {yosys_excludes}")
        copyBSVVerilog(cli.bluespec_dir, srcpath, yosys_excludes, False)

        if not os.path.exists(reportspath):
            os.makedirs(reportspath)

        yosys_cmd = f"yosys -q -p \"read_verilog {srcpath}/*.v; "
        if synth:
            yosys_cmd += f"tee -o {reportspath}/synthesis.log "
            yosys_cmd += f"synth_{synthtarget} -top {cli.topModule} -json {cli.projectname}.json"
            yosys_cmd += "\""
        else:
            print(f"yosys custom commands: {cli.yosys_commands}")
            yosys_cmd += f"{cli.yosys_commands}"
            yosys_cmd += "\""

        print("Starting yosys...\n")
        print("YOSYS_CMD:" + yosys_cmd)
        p = subprocess.Popen(yosys_cmd, shell=True, stdout=subprocess.PIPE).stdout.read()
        res = p.decode()
        print("\nYosys finished")
        print("-------------------------------------------------------------------------------------")

        if synth:
            pnr_cmd = f"nextpnr-{synthtarget} "
            pnr_cmd += f"--{constraintsid} {constraints_file} "
            pnr_cmd += f"--json {cli.projectname}.json "
            pnr_cmd += f"--{mkYosys.pnr_outfiles[synthtarget][0]} {cli.projectname}_synth.{mkYosys.pnr_outfiles[synthtarget][1]} "
            pnr_cmd += f"--report {reportspath}/pnr.json "
            pnr_cmd += f"--log {reportspath}/pnr_cli.log "
            # add additional user pnr args
            pnr_cmd += f"{cli.pnr_options} " 

            print("Starting Place and Route...\n")
            # print("PNR cmd: " + pnr_cmd)
            p = subprocess.Popen(pnr_cmd, shell=True, stderr=subprocess.PIPE).stderr.read() # nextpnr writes info to stderr??
            s = p.decode()
            success = re.search(r"Program finished normally", s)
            # print some basic stats 
            if success:
                print([maxf for maxf in s.split('\n') if "Max frequency" in maxf][-1])

            success_report = "successfully" if success else "with errors"
            print(f"\nPlace and Route finished {success_report}")

            if success:
                print("-------------------------------------------------------------------------------------")
                print("Starting bitstream generation...\n")
                bitstream_packer = mkYosys.bitstream_packing[synthtarget][0]
                bitstream_fileending = mkYosys.bitstream_packing[synthtarget][1]
                pack_cmd = f"{bitstream_packer} {cli.projectname}_synth.{mkYosys.pnr_outfiles[synthtarget][1]} {cli.projectname}.{bitstream_fileending}"
                print(f"pack command: {pack_cmd}")
                p = subprocess.Popen(pack_cmd, shell=True, stderr=subprocess.PIPE).stderr.read()
                s = p.decode()
                if s != "":
                    print(s)
                print(f"\nBitstream generation finished")
            else: 
                return
            
        if cli.render_netlist:
            netlist_file = f"{cli.projectname}.json" # default netlist output as configured above
            render_output = f"{cli.projectname}.svg"
            if len(cli.render_netlist) == 2:
                netlist_file = cli.render_netlist[-1]
            elif len(cli.render_netlist) == 1:
                render_output = cli.render_netlist[-1]
            elif len(cli.render_netlist) != 0:
                print(cli.render_netlist)
                print(f"Only options for svg rendering: <out-file> <netlist-file>")
                return
            render_cmd = f"netlistsvg {netlist_file} -o {render_output}"
            p = subprocess.Popen(render_cmd, shell=True, stdout=subprocess.PIPE).stdout.read()
            s = p.decode()
            if s != "":
                print(s)  
            success = not re.search(r"Error", s)
            print(f"\nRendered netlist to svgfile" if success else " \nFailed to render netlist")

            if success and cli.render_convert:
                import cairosvg
                if cli.render_convert == "pdf":
                    cairosvg.svg2pdf(file_obj=open(render_output, "rb"), write_to=f"{cli.projectname}.pdf")
                if cli.render_convert == "png":
                    cairosvg.svg2png(url=render_output, write_to=f"{cli.projectname}.png")


        print(f"Wrote reports to {reportspath}")

commands = {'mkVivado': mkVivado, 'mkYosys': mkYosys}

def find_bluespec():
    pattern = "Bluespec directory: (.*)"
    t = subprocess.Popen("bsc -help", shell=True, stdout=subprocess.PIPE).stdout.read()
    s = t.decode()
    for l in s.splitlines():
        m = re.match(pattern, l)
        if m:
            return m.group(1)
    else:
        return ''


def main():
    parser = argparse.ArgumentParser(description='Tools for BSV developers.')
    parser.add_argument('base_dir', type=str)
    parser.add_argument('command', type=str, choices=commands.keys())
    parser.add_argument('projectname', type=str)
    parser.add_argument('topModule', type=str)
    parser.add_argument('--verilog_dir', nargs='+', default="verilog", type=str)
    parser.add_argument('--vendor', default=vendor, type=str)
    parser.add_argument('--bluespec_dir', default=os.getenv('BLUESPECDIR', find_bluespec()), type=str)
    parser.add_argument('--exclude', nargs='+', default="", type=str)
    parser.add_argument('--additional', nargs='+', default="", type=str)
    parser.add_argument('--includes', nargs='+', default="", type=str)
    parser.add_argument('--constraints', nargs='+', default="", type=str)

    # options exclusive to mkYosys command
    yosys_group = parser.add_argument_group("mkYosys", description="Since yosys encompassed a lot of features, here are some dedicated args to customize the flow. See the examples on how to use this command.")
    yosys_group.add_argument('--synth_and_target', help="Add this to enable synthesis with specified target", default="", choices=mkYosys.valid_synth_targets, type=str)
    yosys_group.add_argument('--pnr_options', help="Arguments to pass to nextpnr besides the default output/input file handling. This only takes effect if --synth_and_target is passed as well", default="", type=str)
    yosys_group.add_argument('--yosys_commands', help="Use to run arbitrary yosys commands for the generated verilog. Only takes effect if --synth_and_target is not passed", default="", type=str)
    yosys_group.add_argument('--render_netlist', help="The netlist produced by yosys can be rendered to svg by \"netlistsvg\". If the netlist is created by a command in --yosys_commands, the filename can be passed here.", nargs='*', default="", type=str)
    yosys_group.add_argument('--render_convert', help="The generated svg can be converted for easier usability", default="", choices=mkYosys.valid_render_exts, type=str)

    cli = parser.parse_args()

    if cli.bluespec_dir == '':
        print("BLUESPEC_DIR is missing and could not be determined.")
        sys.exit(1)

    commands[cli.command](cli)

if __name__ == '__main__':
    main()
