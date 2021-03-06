/**
 * SPDX-FileCopyrightText: Copyright © 2020 The University of Texas at Austin
 * SPDX-FileContributor: Xinya Zhang <xinyazhang@utexas.edu>
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
/** @file MaxRectsBinPack.cpp
	@author Jukka Jylänki

	@brief Implements different bin packer algorithms that use the MAXRECTS data structure.

	This work is released to Public Domain, do whatever you want with it.
*/
#include <algorithm>
#include <utility>
#include <iostream>
#include <limits>

#include <cassert>
#include <cstring>
#include <cmath>

#include "MaxRectsBinPackReal.h"
#include "FreeRectangleManager.h"

namespace rbp {

using namespace std;


MaxRectsBinPack::MaxRectsBinPack()
:binWidth(0),
binHeight(0)
{
}

MaxRectsBinPack::MaxRectsBinPack(double width, double height, bool allowFlip)
{
	Init(width, height, allowFlip);
}

void MaxRectsBinPack::Init(double width, double height, bool allowFlip)
{
	binAllowFlip = allowFlip;
	binWidth = width;
	binHeight = height;

	Rect n;
	n.x = 0;
	n.y = 0;
	n.width = width;
	n.height = height;

	usedRectangles.clear();

	frm_ = std::make_shared<FreeRectangleManager>(n);
}

Rect MaxRectsBinPack::Insert(double width, double height, FreeRectChoiceHeuristic method, void *cookie)
{
	Rect newNode;
	// Unused in this function. We don't need to know the score after finding the position.
	double score1 = std::numeric_limits<double>::max();
	double score2 = std::numeric_limits<double>::max();
	switch(method)
	{
		case RectBestShortSideFit: newNode = FindPositionForNewNodeBestShortSideFit(width, height, score1, score2); break;
		case RectBottomLeftRule: newNode = FindPositionForNewNodeBottomLeft(width, height, score1, score2); break;
		case RectContactPointRule: newNode = FindPositionForNewNodeContactPoint(width, height, score1); break;
		case RectBestLongSideFit: newNode = FindPositionForNewNodeBestLongSideFit(width, height, score2, score1); break;
		case RectBestAreaFit: newNode = FindPositionForNewNodeBestAreaFit(width, height, score1, score2); break;
	}

	if (newNode.height == 0)
		return newNode;

	newNode.cookie = cookie;
	PlaceRect(newNode);

	return newNode;
}

void MaxRectsBinPack::Insert(std::vector<RectSize> rects, std::vector<Rect> &dst, FreeRectChoiceHeuristic method)
{
	dst.clear();

	while(rects.size() > 0)
	{
		double bestScore1 = std::numeric_limits<double>::max();
		double bestScore2 = std::numeric_limits<double>::max();
		int bestRectIndex = -1;
		Rect bestNode;

#if 0
		for(size_t i = 0; i < rects.size(); ++i)
		{
			double score1;
			double score2;
			Rect newNode = ScoreRect(rects[i].width, rects[i].height, method, score1, score2);

			if (score1 < bestScore1 || (score1 == bestScore1 && score2 < bestScore2))
			{
				bestScore1 = score1;
				bestScore2 = score2;
				bestNode = newNode;
				bestRectIndex = i;
			}
		}

		if (bestRectIndex == -1)
			return;
#else
		std::vector<double> score1s(rects.size());
		std::vector<double> score2s(rects.size());
#pragma omp parallel for
		for(size_t i = 0; i < rects.size(); ++i) {
			ScoreRect(rects[i].width, rects[i].height, method, score1s[i], score2s[i]);
		}

		for(size_t i = 0; i < rects.size(); ++i) {
			auto score1 = score1s[i];
			auto score2 = score2s[i];
			if (score1 < bestScore1 || (score1 == bestScore1 && score2 < bestScore2)) {
				bestScore1 = score1;
				bestScore2 = score2;
				bestRectIndex = i;
			}
		}
		if (bestRectIndex == -1)
			return;
		double score1, score2;
		bestNode = ScoreRect(rects[bestRectIndex].width, rects[bestRectIndex].height, method, score1, score2);
#endif

		bestNode.cookie = rects[bestRectIndex].cookie;
		PlaceRect(bestNode);
		dst.push_back(bestNode);
		rects.erase(rects.begin() + bestRectIndex);
	}
}

void MaxRectsBinPack::PlaceRect(const Rect &node)
{
#if 0
	size_t numRectanglesToProcess = freeRectangles.size();
	std::cerr << "***** First Prune *****" << std::endl;
	PruneFreeList(freeRectangles);

	for(size_t i = 0; i < numRectanglesToProcess; ++i)
	{
		std::vector<Rect> newNodes;
		if (SplitFreeNode(freeRectangles[i], node, newNodes)) {
			freeRectangles.erase(freeRectangles.begin() + i);
			--i;
			--numRectanglesToProcess;
		}
		PruneFreeList(newNodes, false);
		freeRectangles.reserve(freeRectangles.size() + newNodes.size()); 
		freeRectangles.insert(freeRectangles.end(), newNodes.begin(), newNodes.end());
	}

	std::cerr << "***** Secondary Prune *****" << std::endl;
	PruneFreeList(freeRectangles);
#else
	frm_->PlaceRect(node);
#endif
	usedRectangles.push_back(node);
}

Rect MaxRectsBinPack::ScoreRect(double width, double height, FreeRectChoiceHeuristic method, double &score1, double &score2) const
{
	Rect newNode;
	score1 = std::numeric_limits<double>::max();
	score2 = std::numeric_limits<double>::max();
	switch(method)
	{
	case RectBestShortSideFit: newNode = FindPositionForNewNodeBestShortSideFit(width, height, score1, score2); break;
	case RectBottomLeftRule: newNode = FindPositionForNewNodeBottomLeft(width, height, score1, score2); break;
	case RectContactPointRule: newNode = FindPositionForNewNodeContactPoint(width, height, score1);
		score1 = -score1; // Reverse since we are minimizing, but for contact podouble score bigger is better.
		break;
	case RectBestLongSideFit: newNode = FindPositionForNewNodeBestLongSideFit(width, height, score2, score1); break;
	case RectBestAreaFit: newNode = FindPositionForNewNodeBestAreaFit(width, height, score1, score2); break;
	}

	// Cannot fit the current rectangle.
	if (newNode.height == 0)
	{
		score1 = std::numeric_limits<double>::max();
		score2 = std::numeric_limits<double>::max();
	}

	return newNode;
}

/// Computes the ratio of used surface area.
float MaxRectsBinPack::Occupancy() const
{
	double usedSurfaceArea = 0;
	for(size_t i = 0; i < usedRectangles.size(); ++i)
		usedSurfaceArea += usedRectangles[i].width * usedRectangles[i].height;

	return (float)usedSurfaceArea / (binWidth * binHeight);
}

Rect MaxRectsBinPack::FindPositionForNewNodeBottomLeft(double width, double height, double &bestY, double &bestX) const
{
	Rect bestNode;
	memset(&bestNode, 0, sizeof(Rect));

	bestY = std::numeric_limits<double>::max();
	bestX = std::numeric_limits<double>::max();

	for(size_t i = 0; i < frm_->size(); ++i)
	{
		const auto& frect = frm_->getFree(i);
		// Try to place the rectangle in upright (non-flipped) orientation.
		if (frect.width >= width && frect.height >= height)
		{
			double topSideY = frect.y + height;
			if (topSideY < bestY || (topSideY == bestY && frect.x < bestX))
			{
				bestNode.x = frect.x;
				bestNode.y = frect.y;
				bestNode.width = width;
				bestNode.height = height;
				bestNode.rotated = false;
				bestY = topSideY;
				bestX = frect.x;
			}
		}
		if (binAllowFlip && frect.width >= height && frect.height >= width)
		{
			double topSideY = frect.y + width;
			if (topSideY < bestY || (topSideY == bestY && frect.x < bestX))
			{
				bestNode.x = frect.x;
				bestNode.y = frect.y;
				bestNode.width = height;
				bestNode.height = width;
				bestNode.rotated = true;
				bestY = topSideY;
				bestX = frect.x;
			}
		}
	}
	return bestNode;
}

Rect MaxRectsBinPack::FindPositionForNewNodeBestShortSideFit(double width, double height,
	double &bestShortSideFit, double &bestLongSideFit) const
{
	Rect bestNode;
	memset(&bestNode, 0, sizeof(Rect));

	bestShortSideFit = std::numeric_limits<double>::max();
	bestLongSideFit = std::numeric_limits<double>::max();

	for(size_t i = 0; i < frm_->size(); ++i)
	{
		const auto& frect = frm_->getFree(i);
		// Try to place the rectangle in upright (non-flipped) orientation.
		if (frect.width >= width && frect.height >= height)
		{
			double leftoverHoriz = abs(frect.width - width);
			double leftoverVert = abs(frect.height - height);
			double shortSideFit = min(leftoverHoriz, leftoverVert);
			double longSideFit = max(leftoverHoriz, leftoverVert);

			if (shortSideFit < bestShortSideFit || (shortSideFit == bestShortSideFit && longSideFit < bestLongSideFit))
			{
				bestNode.x = frect.x;
				bestNode.y = frect.y;
				bestNode.width = width;
				bestNode.height = height;
				bestNode.rotated = false;
				bestShortSideFit = shortSideFit;
				bestLongSideFit = longSideFit;
			}
		}

		if (binAllowFlip && frect.width >= height && frect.height >= width)
		{
			double flippedLeftoverHoriz = abs(frect.width - height);
			double flippedLeftoverVert = abs(frect.height - width);
			double flippedShortSideFit = min(flippedLeftoverHoriz, flippedLeftoverVert);
			double flippedLongSideFit = max(flippedLeftoverHoriz, flippedLeftoverVert);

			if (flippedShortSideFit < bestShortSideFit || (flippedShortSideFit == bestShortSideFit && flippedLongSideFit < bestLongSideFit))
			{
				bestNode.x = frect.x;
				bestNode.y = frect.y;
				bestNode.width = height;
				bestNode.height = width;
				bestNode.rotated = true;
				bestShortSideFit = flippedShortSideFit;
				bestLongSideFit = flippedLongSideFit;
			}
		}
	}
	return bestNode;
}

Rect MaxRectsBinPack::FindPositionForNewNodeBestLongSideFit(double width, double height,
	double &bestShortSideFit, double &bestLongSideFit) const
{
	Rect bestNode;
	memset(&bestNode, 0, sizeof(Rect));

	bestShortSideFit = std::numeric_limits<double>::max();
	bestLongSideFit = std::numeric_limits<double>::max();

	for(size_t i = 0; i < frm_->size(); ++i)
	{
		const auto& frect = frm_->getFree(i);
		// Try to place the rectangle in upright (non-flipped) orientation.
		if (frect.width >= width && frect.height >= height)
		{
			double leftoverHoriz = abs(frect.width - width);
			double leftoverVert = abs(frect.height - height);
			double shortSideFit = min(leftoverHoriz, leftoverVert);
			double longSideFit = max(leftoverHoriz, leftoverVert);

			if (longSideFit < bestLongSideFit || (longSideFit == bestLongSideFit && shortSideFit < bestShortSideFit))
			{
				bestNode.x = frect.x;
				bestNode.y = frect.y;
				bestNode.width = width;
				bestNode.height = height;
				bestNode.rotated = false;
				bestShortSideFit = shortSideFit;
				bestLongSideFit = longSideFit;
			}
		}

		if (binAllowFlip && frect.width >= height && frect.height >= width)
		{
			double leftoverHoriz = abs(frect.width - height);
			double leftoverVert = abs(frect.height - width);
			double shortSideFit = min(leftoverHoriz, leftoverVert);
			double longSideFit = max(leftoverHoriz, leftoverVert);

			if (longSideFit < bestLongSideFit || (longSideFit == bestLongSideFit && shortSideFit < bestShortSideFit))
			{
				bestNode.x = frect.x;
				bestNode.y = frect.y;
				bestNode.width = height;
				bestNode.height = width;
				bestNode.rotated = true;
				bestShortSideFit = shortSideFit;
				bestLongSideFit = longSideFit;
			}
		}
	}
	return bestNode;
}

Rect MaxRectsBinPack::FindPositionForNewNodeBestAreaFit(double width, double height,
	double &bestAreaFit, double &bestShortSideFit) const
{
	Rect bestNode;
	memset(&bestNode, 0, sizeof(Rect));

	bestAreaFit = std::numeric_limits<double>::max();
	bestShortSideFit = std::numeric_limits<double>::max();

	for(size_t i = 0; i < frm_->size(); ++i)
	{
		const auto& frect = frm_->getFree(i);
		double areaFit = frect.width * frect.height - width * height;

		// Try to place the rectangle in upright (non-flipped) orientation.
		if (frect.width >= width && frect.height >= height)
		{
			double leftoverHoriz = abs(frect.width - width);
			double leftoverVert = abs(frect.height - height);
			double shortSideFit = min(leftoverHoriz, leftoverVert);

			if (areaFit < bestAreaFit || (areaFit == bestAreaFit && shortSideFit < bestShortSideFit))
			{
				bestNode.x = frect.x;
				bestNode.y = frect.y;
				bestNode.width = width;
				bestNode.height = height;
				bestNode.rotated = false;
				bestShortSideFit = shortSideFit;
				bestAreaFit = areaFit;
			}
		}

		if (binAllowFlip && frect.width >= height && frect.height >= width)
		{
			double leftoverHoriz = abs(frect.width - height);
			double leftoverVert = abs(frect.height - width);
			double shortSideFit = min(leftoverHoriz, leftoverVert);

			if (areaFit < bestAreaFit || (areaFit == bestAreaFit && shortSideFit < bestShortSideFit))
			{
				bestNode.x = frect.x;
				bestNode.y = frect.y;
				bestNode.width = height;
				bestNode.height = width;
				bestNode.rotated = true;
				bestShortSideFit = shortSideFit;
				bestAreaFit = areaFit;
			}
		}
	}
	return bestNode;
}

/// Returns 0 if the two intervals i1 and i2 are disjoint, or the length of their overlap otherwise.
double CommonIntervalLength(double i1start, double i1end, double i2start, double i2end)
{
	if (i1end < i2start || i2end < i1start)
		return 0;
	return min(i1end, i2end) - max(i1start, i2start);
}

double MaxRectsBinPack::ContactPointScoreNode(double x, double y, double width, double height) const
{
	double score = 0;

	if (x == 0 || x + width == binWidth)
		score += height;
	if (y == 0 || y + height == binHeight)
		score += width;

	for(size_t i = 0; i < usedRectangles.size(); ++i)
	{
		if (usedRectangles[i].x == x + width || usedRectangles[i].x + usedRectangles[i].width == x)
			score += CommonIntervalLength(usedRectangles[i].y, usedRectangles[i].y + usedRectangles[i].height, y, y + height);
		if (usedRectangles[i].y == y + height || usedRectangles[i].y + usedRectangles[i].height == y)
			score += CommonIntervalLength(usedRectangles[i].x, usedRectangles[i].x + usedRectangles[i].width, x, x + width);
	}
	return score;
}

Rect MaxRectsBinPack::FindPositionForNewNodeContactPoint(double width, double height, double &bestContactScore) const
{
	Rect bestNode;
	memset(&bestNode, 0, sizeof(Rect));

	bestContactScore = -1;

	for(size_t i = 0; i < frm_->size(); ++i)
	{
		const auto& frect = frm_->getFree(i);
		// Try to place the rectangle in upright (non-flipped) orientation.
		if (frect.width >= width && frect.height >= height)
		{
			double score = ContactPointScoreNode(frect.x, frect.y, width, height);
			if (score > bestContactScore)
			{
				bestNode.x = frect.x;
				bestNode.y = frect.y;
				bestNode.width = width;
				bestNode.height = height;
				bestNode.rotated = false;
				bestContactScore = score;
			}
		}
		if (frect.width >= height && frect.height >= width)
		{
			double score = ContactPointScoreNode(frect.x, frect.y, height, width);
			if (score > bestContactScore)
			{
				bestNode.x = frect.x;
				bestNode.y = frect.y;
				bestNode.width = height;
				bestNode.height = width;
				bestNode.rotated = true;
				bestContactScore = score;
			}
		}
	}
	return bestNode;
}

}
