/**
 * Copyright (C) 2020 The University of Texas at Austin
 * SPDX-License-Identifier: BSD-3-Clause or GPL-2.0-or-later
 */
#ifndef GEOPICK_PICK2D_H
#define GEOPICK_PICK2D_H

#include <Eigen/Core>
#include <vector>
#include <functional>
#include <unordered_map>

void geopick(const Eigen::MatrixXd& V,
	     std::vector<std::reference_wrapper<const Eigen::MatrixXi>> Fs, // Copy matrix is way too expensive
             Eigen::MatrixXd &outV,
             Eigen::MatrixXi &outF,
             std::unordered_map<int, int> *map = nullptr
             );

#endif
