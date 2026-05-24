#!/usr/bin/env python3

import sys
import subprocess
import argparse
import os
import shutil
import glob
import subprocess
import re
import json
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
            addLicenseHeader(shutil.copyfile(filename, os.path.join(dest, os.path.basename(filename))))
    if includevivado:
        for filename in glob.glob(os.path.join(src, 'Verilog.Vivado', '*.v')):
            if not os.path.basename(filename) in exclude:
                addLicenseHeader(shutil.copyfile(filename, os.path.join(dest, os.path.basename(filename))))

def copyBSVVerilogFromUse(src, use_file, dest, exclude="", prefer_vivado=False):
    if not os.path.exists(use_file):
        print(f"Could not find Bluespec module use file: {use_file}")
        sys.exit(1)

    search_dirs = ['Verilog.Vivado', 'Verilog'] if prefer_vivado else ['Verilog', 'Verilog.Vivado']
    seen_modules = set()

    with open(use_file, "r") as use_handle:
        for line in use_handle:
            module_name = line.strip()
            if not module_name or module_name in seen_modules:
                continue
            seen_modules.add(module_name)

            copied = False
            for verilog_dir in search_dirs:
                candidate = os.path.join(src, verilog_dir, f"{module_name}.v")
                if os.path.exists(candidate):
                    if not os.path.basename(candidate) in exclude:
                        addLicenseHeader(shutil.copyfile(candidate, os.path.join(dest, os.path.basename(candidate))))
                    copied = True
                    break

            if not copied:
                print(f"Could not find Bluespec Verilog for used module: {module_name}")
                sys.exit(1)


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

def copyVerilogFiles(src, dest, exclude):
    for path in src:
        if path.endswith('.v'):
            if not os.path.basename(path) in exclude:
                flattenVerilogIncludes(path, dest)
        else:
            for filename in glob.glob(os.path.join(path, '*.v')):
                if not os.path.basename(filename) in exclude:
                    flattenVerilogIncludes(filename, dest)

def findUseFile(search_paths, top_module):
    for path in search_paths:
        if path.endswith('.use') and os.path.exists(path):
            return path

        candidate = os.path.join(path, f"{top_module}.use")
        if os.path.exists(candidate):
            return candidate

    return ""

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
                m = re.search(r'^\s*`include \"(.*)\"', l)
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

def processInterfaces(path):
    ifcs = dict()
    ifc_cmd = ""
    with open(path) as ifcs_file:
        ifcs = json.loads(ifcs_file.read())
    if not ifcs:
        print(f"No interface specification found at {path}")
        return ifc_cmd

    for ifc in ifcs.keys():
        ifc_name = ifc
        ifc_abstype = ifcs[ifc]["abstraction_type"]
        ifc_bustype = ifcs[ifc]["bus_type"]
        ifc_pins = ifcs[ifc]["pins"]
        ifc_mode = ifcs[ifc].get("mode", None)
        ifc_cmd += f"ipx::add_bus_interface {ifc_name} [ipx::current_core]\n"
        ifc_cmd += f"set_property abstraction_type_vlnv {ifc_abstype} [ipx::get_bus_interfaces {ifc_name} -of_objects [ipx::current_core]]\n"
        ifc_cmd += f"set_property bus_type_vlnv {ifc_bustype} [ipx::get_bus_interfaces {ifc_name} -of_objects [ipx::current_core]]\n"
        ifc_cmd += f"set_property display_name {ifc_name} [ipx::get_bus_interfaces {ifc_name} -of_objects [ipx::current_core]]\n"
        if ifc_mode is not None:
            ifc_cmd += f"set_property interface_mode {ifc_mode} [ipx::get_bus_interfaces {ifc_name} -of_objects [ipx::current_core]]\n"
        for pin_map in ifc_pins:
            pin_name, map_type = next(iter(pin_map.items()))
            ifc_cmd += f"ipx::add_port_map {map_type} [ipx::get_bus_interfaces {ifc_name} -of_objects [ipx::current_core]]\n"
            ifc_cmd += f"set_property physical_name {pin_name} [ipx::get_port_maps {map_type} -of_objects [ipx::get_bus_interfaces {ifc_name} -of_objects [ipx::current_core]]]\n"

    return ifc_cmd


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
    additional += processInterfaces(cli.interfaces)

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

class mkVivadoTCL():

    create_project = """
set project_dir {project_dir}
set project_name {project_name}
set src_path {src_path}
# optional variables
set script_path {{{script_path}}}
set constr_path {{{constr_path}}}

puts "Creating project $project_name at path $project_dir"
create_project -part {part} -force $project_name $project_dir

read_verilog [glob -directory $src_path *.v]

if {{[file exists $constr_path]}} {{
    read_xdc $constr_path
}}
puts "Script path: $script_path"
if {{[file exists $script_path]}} {{
    source $script_path
}}

close_project
exit 0
"""

    def __init__(self, cli):
        proj_path = os.path.join(os.getcwd(), cli.projectname)
        src_path = os.path.join(proj_path, "src")

        if not os.path.exists(src_path):
            os.makedirs(src_path)

        script_path = ""
        if(os.path.exists(cli.script)):
            script_path = cli.script

        constraints_path = ""
        constraints = cli.constraints[0] #TODO
        if(os.path.exists(constraints)):
            constraints_path = constraints

        # add explicitly passed verilog files or if directory passed, all verilog files in dir
        source_files = []
        for path in cli.includes:
            if path.endswith('.v'):
                source_files.append(path)
            else:
                for filename in glob.glob(os.path.join(path, '*.v')):
                    source_files.append(filename)

        copyVerilog(cli.verilog_dir, src_path, cli.exclude)
        if cli.includes:
            copyVerilog(cli.includes, src_path, cli.exclude)
        copyBSVVerilog(cli.bluespec_dir, src_path, "main.v")

        if which("vivado") is None:
            print("Could not find \"vivado\". Make sure Vivado is in the path.")
            sys.exit(1)
        with open('temp.tcl', "w+") as f:
            f.write(self.create_project.format(
                    project_dir=proj_path, 
                    project_name=cli.projectname, 
                    src_path=src_path, 
                    part=cli.part, 
                    constr_path=constraints_path,
                    script_path=script_path
                )
            )
        t = subprocess.Popen("vivado" + " -mode batch -source temp.tcl -nojournal -nolog", shell=True, stdout=subprocess.PIPE).stdout.read()
        os.remove('temp.tcl')
        s = t.decode()
        print(s)

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
            TriState.v
        """
        print(f"Not including following sources due to incompatibility with yosys: {yosys_excludes}")
        copyBSVVerilog(cli.bluespec_dir, srcpath, yosys_excludes, False)

        if not os.path.exists(reportspath):
            os.makedirs(reportspath)

        #AAAAA
        print(f"Fixing inout ports ({srcpath})")
        p = subprocess.Popen(f"perl {cli.base_dir}/basicinout.pl {srcpath}/*.v ", shell=True, stdout=subprocess.PIPE).stdout.read()
        res = p.decode()
        #AAAAA

        yosys_cmd = f"yosys -q -p \"read_verilog {srcpath}/*.v; "
        if synth:
            yosys_cmd += f"tee -o {reportspath}/synthesis.log "
            yosys_cmd += f"synth_{synthtarget} -top {cli.topModule} -json {cli.projectname}.json;"
            # yosys_cmd += f"select -module {cli.topModule}; write_verilog synthd.v;"
            yosys_cmd += "\""
        else:
            print(f"yosys custom commands: {cli.yosys_commands}")
            yosys_cmd += f"{cli.yosys_commands}"
            yosys_cmd += "\""

        print("Starting yosys...\n")
        print("YOSYS_CMD: " + yosys_cmd)
        p = subprocess.Popen(yosys_cmd, shell=True, stdout=subprocess.PIPE).stdout.read()
        res = p.decode()
        print(f"\nYosys finished, see: {reportspath}" )
        print("-------------------------------------------------------------------------------------")

        if synth:
            pnr_cmd = f"nextpnr-{synthtarget} "
            pnr_cmd += f"--lpf-allow-unconstrained "
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
                pack_cmd = f"{bitstream_packer} --compress {cli.projectname}_synth.{mkYosys.pnr_outfiles[synthtarget][1]} {cli.projectname}.{bitstream_fileending}"
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

class mkExportVerilog():

    def __init__(self, cli):
        export_root = cli.output_dir if cli.output_dir else os.path.join("export", cli.projectname)
        proj_path = os.path.join(os.getcwd(), export_root)
        src_path = os.path.join(proj_path, "src")

        if not os.path.exists(src_path):
            os.makedirs(src_path)
        else:
            print(f"{src_path} already exists")
            return

        use_file = findUseFile(cli.verilog_dir, cli.topModule)
        if use_file == "":
            print(f"Could not find {cli.topModule}.use in {cli.verilog_dir}. Re-run compile_top with -show-module-use.")
            sys.exit(1)

        copyVerilogFiles(cli.verilog_dir, src_path, cli.exclude)
        if cli.includes:
            copyVerilogFiles(cli.includes, src_path, cli.exclude)
        copyBSVVerilogFromUse(cli.bluespec_dir, use_file, src_path, cli.exclude, cli.prefer_vivado_bsv)

        print(f"Exported sources to {proj_path}")

commands = {'mkVivado': mkVivado, 'mkVivadoTCL': mkVivadoTCL, 'mkYosys': mkYosys, 'mkExportVerilog': mkExportVerilog}

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
    
    vivado_ip = parser.add_argument_group("mkVivado", description="Options for vivado IP generation customization")
    vivado_ip.add_argument('--verilog_dir', nargs='+', default="verilog", type=str)
    vivado_ip.add_argument('--vendor', default=vendor, type=str)
    vivado_ip.add_argument('--bluespec_dir', default=os.getenv('BLUESPECDIR', find_bluespec()), type=str)
    vivado_ip.add_argument('--exclude', nargs='+', default="", type=str)
    vivado_ip.add_argument('--additional', nargs='+', default="", type=str)
    vivado_ip.add_argument('--includes', nargs='+', default="", type=str)
    vivado_ip.add_argument('--constraints', nargs='+', default="", type=str)
    vivado_ip.add_argument('--interfaces', default="", type=str)

    # options exclusive to mkYosys command
    yosys_group = parser.add_argument_group("mkYosys", description="Since yosys encompassed a lot of features, here are some dedicated args to customize the flow. See the examples on how to use this command.")
    yosys_group.add_argument('--synth_and_target', help="Add this to enable synthesis with specified target", default="", choices=mkYosys.valid_synth_targets, type=str)
    yosys_group.add_argument('--pnr_options', help="Arguments to pass to nextpnr besides the default output/input file handling. This only takes effect if --synth_and_target is passed as well", default="", type=str)
    yosys_group.add_argument('--yosys_commands', help="Use to run arbitrary yosys commands for the generated verilog. Only takes effect if --synth_and_target is not passed", default="", type=str)
    yosys_group.add_argument('--render_netlist', help="The netlist produced by yosys can be rendered to svg by \"netlistsvg\". If the netlist is created by a command in --yosys_commands, the filename can be passed here.", nargs='*', default="", type=str)
    yosys_group.add_argument('--render_convert', help="The generated svg can be converted for easier usability", default="", choices=mkYosys.valid_render_exts, type=str)

    vivado_tcl = parser.add_argument_group("mkVivadoTCL", description="")
    vivado_tcl.add_argument('--part', help="Part number of synthesis target used for project creation", default="xcku3p-ffvb676-2-e", type=str)
    vivado_tcl.add_argument('--script', help="Custom TCL script sourced from created project", default="", required=False, type=str)

    export_group = parser.add_argument_group("mkExportVerilog", description="Options for exporting generated Verilog and Bluespec library Verilog sources")
    export_group.add_argument('--output_dir', default="", type=str)
    export_group.add_argument('--prefer_vivado_bsv', action='store_true', help="Prefer Bluespec Verilog.Vivado library files when both variants exist")

    cli = parser.parse_args()

    if cli.bluespec_dir == '':
        print("BLUESPEC_DIR is missing and could not be determined.")
        sys.exit(1)

    commands[cli.command](cli)

if __name__ == '__main__':
    main()
