#!/bin/bash

./facade.py tools blender --current_trial 21 --dir condor.u3/duet-g1 --puzzle_name duet-g1 \
	--camera_origin 40 -60 -60 \
	--camera_lookat 5 5 0 \
	--camera_up 0 0 -1 \
	--floor_origin 0 0 50 \
	--floor_euler 0 0 180 \
	--light_auto \
	--saveas blender/blender_g1.blend \
	--animation_floor_origin 0 0 50 \
	--animation_end 1352 \
	"$@" \
    -- \
    --remove_vn env rob \
    --enable_autosmooth env rob \
