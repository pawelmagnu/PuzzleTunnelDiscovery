/**
 * SPDX-FileCopyrightText: Copyright © 2020 The University of Texas at Austin
 * SPDX-FileContributor: Xinya Zhang <xinyazhang@utexas.edu>
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "sancheck.h"
#include <igl/readOBJ.h>
#include <igl/writeOBJ.h>
#include <unistd.h>
#include <string>
#include <iostream>
#include <fat/fat.h>

using std::string;
using std::endl;

void usage()
{
	std::cerr << "Options: -i <input OBJ file> -o <output OBJ file> -w <fattening width> -s <scale factor>" << endl;
	std::cerr << "\tscale factor: default to " << fat::default_scale_factor << ", increase this for finer mesh" << endl;
}

int main(int argc, char* argv[])
{
	int opt;
	string ifn, ofn;
	double fatten = 1.0;
	double scale = fat::default_scale_factor;
	bool trianglize = true;
	bool do_sancheck = false;
	while ((opt = getopt(argc, argv, "i:o:w:s:qc")) != -1) {
		switch (opt) {
			case 'i': 
				ifn = optarg;
				break;
			case 'o':
				ofn = optarg;
				break;
			case 'w':
				fatten = atof(optarg);
				break;
			case 's':
				scale = atof(optarg);
				break;
			case 'q':
				trianglize = false;
				break;
			case 'c':
				do_sancheck = true;
				break;
			default:
				usage();
				return -1;
		}
	}
	if (ifn.empty() || ofn.empty()) {
		usage();
		return -1;
	}

	fat::initialize();

	Eigen::MatrixXf IV, OV;
	Eigen::MatrixXi IF, OF;
	if (!igl::readOBJ(ifn, IV, IF)) {
		std::cerr << "Fail to read " << argv[1] << " as OBJ file" << std::endl;
		return -1;
	}
	fat::mkfatter(IV, IF, fatten, OV, OF, trianglize, scale);
	igl::writeOBJ(ofn, OV, OF);
	if (do_sancheck) {
		std::cerr << "SAN Check...";
		san_check(IV, IF, OV, OF, fatten);
	}
	return 0;
}
