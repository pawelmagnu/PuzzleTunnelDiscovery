/**
 * Copyright (C) 2020 The University of Texas at Austin
 * SPDX-License-Identifier: BSD-3-Clause or GPL-2.0-or-later
 */
#ifndef FAT_INTERFACE_H
#define FAT_INTERFACE_H

#include <Eigen/Core>

namespace fat {
	constexpr double default_scale_factor = 4.0;

	void initialize();

	void mkfatter(
			const Eigen::MatrixXf& inV,
			const Eigen::MatrixXi& inF,
			double width,
			Eigen::MatrixXf& outV,
			Eigen::MatrixXi& outF,
			bool trianglize = true,
			double scale = default_scale_factor
	             );
};

#endif
