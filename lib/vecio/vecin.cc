/**
 * SPDX-FileCopyrightText: Copyright © 2020 The University of Texas at Austin
 * SPDX-FileContributor: Xinya Zhang <xinyazhang@utexas.edu>
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "vecin.h"
#include <stdexcept>
#include <fstream>

void vecio::text_read(const std::string& fn, Eigen::VectorXd& HSV)
{
	std::ifstream fin(fn);
	if (!fin.is_open()) {
		throw std::runtime_error("Cannot open file: "+fn+" for read");
	}
	int nnode;
	fin >> nnode;
	HSV.resize(nnode);
	for(int i = 0; i < nnode; i++) {
		double v;
		fin >> v;
		HSV(i) = v;
	}
}
