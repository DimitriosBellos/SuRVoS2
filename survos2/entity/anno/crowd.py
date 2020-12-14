import ast
import pandas as pd
import sys
import math
import os
import numpy as np
import matplotlib.pyplot as plt

# from survos2.frontend.utils import get_img_in_bbox
from survos2.entity.sampler import get_img_in_bbox

import skimage
from skimage import img_as_ubyte
import imageio


def get_window(image_volume, sliceno, xstart, ystart, xend, yend):
    return image_volume[sliceno, xstart:xend, ystart:yend]


session_extract = []


def parse_tuple(string):
    try:
        s = ast.literal_eval(str(string))
        if type(s) == tuple:
            return s
        return
    except:
        return


PATCH_DIM = 64


# uses two volumes of the same dimensions
def generate_splitscreen_movies(
    img_volume, img_volume2, click_coords, output_dir, movie_size=(28, 32, 32)
):
    movie_list = []
    movie_titles = []
    sel_cropped_clicks = []
    for j in range(len(click_coords)):

        sliceno, y, x = click_coords[j]

        d, w, h = movie_size

        slice_start = np.max(sliceno - int(d / 2.0))
        slice_end = sliceno + d

        print("Writing movie from slice {} to {} ".format(slice_start, slice_end))
        print(x, y, w, h, sliceno)

        sel_cropped_clicks.append((sliceno, x, y, w, h))

        frame_list = []

        for k in range(d):
            f_left = get_img_in_bbox(
                img_volume, slice_start + k, int(np.ceil(x)), int(np.ceil(y)), w, h
            )
            f_right = get_img_in_bbox(
                img_volume2, slice_start + k, int(np.ceil(x)), int(np.ceil(y)), w, h
            )

            splitscreen_frame = np.hstack((f_left, f_right))
            splitscreen_frame = skimage.transform.rescale(
                splitscreen_frame, 1.3, order=2
            )

            frame_list.append(splitscreen_frame)

        y_str = str(int(y))  # "{:10.4f}".format(y)
        x_str = str(int(x))  # "{:10.4f}".format(x)

        movie_title = (
            "loc_"
            + str(int(sliceno))
            + "_"
            + x_str
            + "_"
            + y_str
            + "_"
            + "size_"
            + str(movie_size[0])
            + "_"
            + str(movie_size[1])
            + "_"
            + str(movie_size[2])
        )

        writer = imageio.get_writer(
            os.path.join(
                output_dir, "test_ss_" + str(movie_title) + "_" + str(j) + ".gif"
            ),
            fps=10,
        )

        for f in frame_list:
            writer.append_data(img_as_ubyte(f))

        writer.close()

    return movie_list, movie_titles


def ss_movies_test():
    generate_ss_movies = True
    if generate_ss_movies:
        print("Generating {} number of movies.".format(len(centroid_coords)))
        movie_list1, movie_titles = generate_splitscreen_movies(
            wf1, wf2, centroid_coords, movie_size=(28, 32, 32)
        )
    assert len(centroid_coords) == len(movie_list1)


def extract_session_roi(
    roi_data, range_start=0, range_end=50, plot_slices=False, debug_verbose=False
):

    click_data = []  # list of per-session data
    global_idx = 0

    for idx in range(range_start, range_end):
        if idx % 500 == 0:
            print("Extracting roi for parent_data_roi index: {}".format(idx))

        roi_str = roi_data["parent_data_roi"][idx]
        roi = parse_tuple(roi_str)
        sliceno, xstart, ystart, xend, yend = roi
        session_anno = parse_tuple(roi_data["roi_coord_tuples"][idx])
        classification_id, roi_str2, clicks_list = session_anno
        session_extract.append((classification_id, roi_str2))
        clicks_arr = np.array(clicks_list)

        if debug_verbose:
            print("Extracting roi for parent_data_roi index: {}".format(idx))
            print(roi_str)
            print("Session data: {}".format(session_anno))
            print("Roi strings: {}\n {}", roi_str, roi_str2)
            print("Clicks array: {}".format(clicks_arr))
        # extract per-session data and create list of session data
        session = []

        xs = []  # just for visualisation below
        ys = []

        discard_idx = []

        for click_idx in range(clicks_arr.shape[0]):

            x = xstart + clicks_arr[click_idx, 0]
            y = ystart + clicks_arr[click_idx, 1]

            session.append((sliceno, x, y))
            xs.append(x)
            ys.append(y)

        # print(global_idx)
        click_data.extend(session)

        # For viz and debug
        if plot_slices:
            imstack = wf1

            droi = imstack[sliceno, :, :].copy()
            droi = np.fliplr(droi)

            fig = plt.figure()
            ax = fig.add_subplot(111)
            ax.imshow(droi[xstart:xend, ystart:yend])

            plt.scatter(xs, ys, c="red")

    return click_data


def extract_session_roi2(
    imstack,
    zoon_list,
    range_start=0,
    range_end=50,
    plot_slices=False,
    debug_verbose=False,
):

    click_data = []  # list of per-session data
    global_idx = 0

    for idx in range(range_start, range_end):
        if idx % 5000 == 0:
            print("Extracting roi for parent_data_roi index: {}".format(idx))

        zoon_click = zoon_list[idx]
        sliceno, xstart, ystart, xend, yend, x, y = zoon_click

        if debug_verbose:
            print("Extracting roi for parent_data_roi index: {}".format(idx))
            print(roi_str)
            print("Roi strings: {}\n {}", roi_str)
            print("Clicks array: {}".format(clicks_arr))

        session = []
        xs = []
        ys = []

        discard_idx = []

        x = xstart + x
        y = ystart + y

        session.append((sliceno, x, y))
        xs.append(x)
        ys.append(y)

        click_data.extend(session)

        if plot_slices:

            droi = imstack[sliceno, :, :].copy()
            droi = np.fliplr(droi)

            fig = plt.figure()
            ax = fig.add_subplot(111)
            ax.imshow(droi[xstart:xend, ystart:yend])

            plt.scatter(xs, ys, c="red")

    return click_data


def generate_clicklist(click_data_arr, crop_roi, slicestart, sliceend):
    accum = 0
    lengths = []
    click_coords = []

    _, xstart, ystart, xend, yend = crop_roi

    max_x = np.max(click_data_arr[:, 1])
    min_x = np.min(click_data_arr[:, 1])
    x_coords_range = max_x - min_x
    y_coords_range = np.max(click_data_arr[:, 2]) - np.min(click_data_arr[:, 2])

    scale_factor_x = 1  # vol_shape_x / y_coords_range
    scale_factor_y = 1  # vol_shape_y / x_coords_range

    sel_clicks = click_data_arr[
        np.where(
            np.logical_and(
                click_data_arr[:, 0] >= slicestart, click_data_arr[:, 0] <= sliceend
            )
        )
    ]

    return sel_clicks, x_coords_range, y_coords_range


def generate_click_plot_data(img_data, click_coords, patch_size=(40, 40)):
    img_shortlist = []
    img_titles = []

    for j in range(len(click_coords)):
        sliceno, y, x = click_coords[j]
        w, h = patch_size
        sel_cropped_clicks.append((sliceno, x, y, w, h))
        img = get_img_in_bbox(img_data, sliceno, int(np.ceil(x)), int(np.ceil(y)), w, h)

        img_shortlist.append(img)
        img_titles.append(str(int(x)) + "_" + str(int(y)) + "_" + str(sliceno))

    return img_shortlist, img_titles


def generate_full_click_plot_data(img_data, click_coords, patch_size=(40, 40)):

    img_shortlist = []
    img_titles = []
    img_coords = []

    for j in range(len(click_coords)):
        sliceno, y, x = click_coords[j]
        w, h = patch_size
        img_coords.append((sliceno, x, y, w, h))
        img = get_img_in_bbox(img_data, sliceno, int(np.ceil(x)), int(np.ceil(y)), w, h)

        img_shortlist.append(img)
        # y_str = "{:.3f}".format(y)
        # x_str = "{:.3f}".format(x)
        img_titles.append(str(int(x)) + "_" + str(int(y)) + "_" + str(int(sliceno)))

    return img_shortlist, img_titles, img_coords


def generate_cropped_stack(crop_roi):
    cropped_stack = []
    slicestart, sliceend = 0, vol_shape_z
    # scaled_cropped_stack = []

    for sliceno in range(slicestart, sliceend):
        _, xstart, ystart, xend, yend = crop_roi
        print("Slice no.: {}".format(sliceno))
        win_img = get_window(wf1, sliceno, xstart, ystart, xend, yend)
        cropped_stack.append(win_img)
        # scaled_cropped_stack.append(skimage.transform.rescale(win_img, 0.5))

    cropped_stack = np.array(cropped_stack)

    return cropped_stack


def generate_click_plot_data1(img_data, click_coords, patch_size=(40, 40)):
    sel_cropped_clicks = []
    img_shortlist = []
    img_titles = []
    for j in range(len(click_coords)):
        sliceno, y, x = click_coords[j]
        w, h = patch_size
        sel_cropped_clicks.append((sliceno, x, y, w, h))
        img = get_img_in_bbox(img_data, sliceno, int(np.ceil(x)), int(np.ceil(y)), w, h)

        img_shortlist.append(img)
        y_str = "{:10.4f}".format(y)
        x_str = "{:10.4f}".format(x)
        img_titles.append(x_str + " " + y_str + "\n " + "Slice no: " + str(sliceno))

    return img_shortlist, img_titles


def get_img_in_bbox1(image_volume, sliceno, x, y, w, h):
    return image_volume[int(sliceno), x - w : x + w, y - h : y + h]


def generate_clicklist(click_data_arr, crop_roi, slicestart, sliceend):
    accum = 0
    lengths = []
    click_coords = []

    _, xstart, ystart, xend, yend = crop_roi
    max_x = np.max(click_data_arr[:, 1])
    min_x = np.min(click_data_arr[:, 1])
    x_coords_range = max_x - min_x
    y_coords_range = np.max(click_data_arr[:, 2]) - np.min(click_data_arr[:, 2])

    scale_factor_x = 1  # vol_shape_x / y_coords_range
    scale_factor_y = 1  # vol_shape_y / x_coords_range

    sel_clicks = click_data_arr[
        np.where(
            np.logical_and(
                click_data_arr[:, 0] >= slicestart, click_data_arr[:, 0] <= sliceend
            )
        )
    ]

    return sel_clicks, x_coords_range, y_coords_range


def generate_click_plot_data1(img_data, click_coords):
    img_shortlist = []
    img_titles = []

    for j in range(len(click_coords)):

        if j % 5000 == 0:
            print("Generating click plot data: {}".format(j))

        sliceno, y, x = click_coords[j]
        w, h = (100, 100)
        print(x, y, w, h, sliceno)

        img = get_img_in_bbox(img_data, 75, int(np.ceil(x)), int(np.ceil(y)), w, h)
        img_shortlist.append(img)

        y_str = "{:10.4f}".format(y)
        x_str = "{:10.4f}".format(x)
        img_titles.append(x_str + " " + y_str + " " + "Slice no: " + str(sliceno))

    return img_shortlist, img_titles


def generate_click_plot_data(img_data, click_coords):
    img_shortlist = []
    img_titles = []
    for j in range(len(click_coords)):
        if j % 5000 == 0:
            print("Generating click plot data: {}".format(j))
        sliceno, y, x = click_coords[j]
        w, h = (100, 100)
        print(x, y, w, h, sliceno)
        img = get_img_in_bbox(img_data, 75, int(np.ceil(x)), int(np.ceil(y)), w, h)

        img_shortlist.append(img)
        y_str = "{:10.4f}".format(y)
        x_str = "{:10.4f}".format(x)
        img_titles.append(x_str + " " + y_str + " " + "Slice no: " + str(sliceno))
    return img_shortlist, img_titles


def generate_click_plot_data_cropped(img_data, click_coords, bv, patch_size=(40, 40)):
    sel_cropped_clicks = []
    img_shortlist = []
    img_titles = []
    for j in range(len(click_coords)):
        sliceno, y, x = click_coords[j]
        w, h = patch_size

        if sliceno < bv[1] and sliceno > bv[0]:

            sel_cropped_clicks.append((sliceno, x, y, w, h))
            img = get_img_in_bbox(
                img_data, sliceno, int(np.ceil(x)), int(np.ceil(y)), w, h
            )

            img_shortlist.append(img)
            y_str = "{:10.4f}".format(y)
            x_str = "{:10.4f}".format(x)
            img_titles.append(x_str + " " + y_str + "\n " + "Slice no: " + str(sliceno))

    return img_shortlist, img_titles


def get_img_in_bbox2(image_volume, sliceno, x, y, w, h):
    return image_volume[int(sliceno), x - w : x + w, y - h : y + h]


def generate_click_plot_data2(img_data, click_coords, patch_size=(40, 40)):
    sel_cropped_clicks = []

    img_shortlist = []
    img_titles = []
    for j in range(len(click_coords)):
        sliceno, y, x = click_coords[j]
        w, h = patch_size
        # print(x,y,w,h,sliceno)
        sel_cropped_clicks.append((sliceno, x, y, w, h))
        img = get_img_in_bbox(img_data, sliceno, int(np.ceil(x)), int(np.ceil(y)), w, h)

        img_shortlist.append(img)
        # y_str = "{:.3f}".format(y)
        # x_str = "{:.3f}".format(x)
        img_titles.append(str(int(x)) + "_" + str(int(y)) + "_" + str(sliceno))

    return img_shortlist, img_titles


def generate_full_click_plot_data(img_data, click_coords, patch_size=(40, 40)):
    img_shortlist = []
    img_titles = []
    img_coords = []
    for j in range(len(click_coords)):
        sliceno, y, x, c = click_coords[j]
        w, h = patch_size
        # print(x,y,w,h,sliceno)
        img_coords.append((sliceno, x, y, w, h))

        img = get_img_in_bbox(img_data, sliceno, int(np.ceil(x)), int(np.ceil(y)), w, h)

        img_shortlist.append(img)
        # y_str = "{:.3f}".format(y)
        # x_str = "{:.3f}".format(x)
        img_titles.append(
            str(int(x)) + "_" + str(int(y)) + "_" + str(int(sliceno)) + str(c)
        )

    return img_shortlist, img_titles, img_coords


def generate_stacked_click_plot_data(
    img_data_layers, click_coords, patch_size=(32, 32)
):
    img_shortlistA = []
    img_shortlistB = []
    img_titles = []

    img_data1, img_data2 = img_data_layers

    for j in range(len(click_coords)):
        sliceno, y, x = click_coords[j]
        w, h = patch_size
        w = w // 2
        h = h // 2
        # print(x,y,w,h,sliceno)
        sel_cropped_clicks.append((sliceno, x, y, w, h))
        # img1 = get_img_in_bbox(img_data1, sliceno-1, int(np.ceil(x)),int(np.ceil(y)),w,h)
        img2 = get_img_in_bbox(
            img_data1, sliceno, int(np.ceil(x)), int(np.ceil(y)), w, h
        )
        # img3 = get_img_in_bbox(img_data1, sliceno-1, int(np.ceil(x)),int(np.ceil(y)),w,h)

        # stacked_img = np.stack((img1, img2, img3), axis=-1)

        img_shortlistA.append(img2)

        # img1 = get_img_in_bbox(img_data1, sliceno-1, int(np.ceil(x)),int(np.ceil(y)),w,h)
        # img2 = get_img_in_bbox(img_data1, sliceno, int(np.ceil(x)),int(np.ceil(y)),w,h)
        # img3 = get_img_in_bbox(img_data1, sliceno+1, int(np.ceil(x)),int(np.ceil(y)),w,h)

        img1 = get_img_in_bbox(
            img_data2, sliceno - 1, int(np.ceil(x)), int(np.ceil(y)), w, h
        )
        img2 = get_img_in_bbox(
            img_data1, sliceno, int(np.ceil(x)), int(np.ceil(y)), w, h
        )
        img3 = get_img_in_bbox(
            img_data2, sliceno - 1, int(np.ceil(x)), int(np.ceil(y)), w, h
        )

        stacked_img = np.stack((img1, img2, img3), axis=-1)

        img_shortlistB.append(stacked_img)

        # Generate a list of titles
        y_str = "{:10.4f}".format(y)
        x_str = "{:10.4f}".format(x)

        img_titles.append(x_str + " " + y_str + "\n " + "Slice no: " + str(sliceno))
        img_shortlists = [img_shortlistA, img_shortlistB]

    return img_shortlists, img_titles


"""
change the underlying bb rep from center + w,h,d to lbl to utr
resample z? (x 5?) then resize the image?
"""


def generate_wide_plot_data(
    img_data,
    click_coords,
    wide_patch_pos=(63, 650, 650),
    z_depth=3,
    patch_size=(40, 200, 200),
):
    img_titles = []
    patch_size = np.array(patch_size)
    sliceno, x, y = wide_patch_pos

    z_depth, p_x, p_y = patch_size
    w = int(p_x / 2.0)
    h = int(p_y / 2.0)
    print("x y w h, sliceno: {}".format((x, y, w, h, sliceno)))
    # sel_cropped_clicks.append((sliceno, x,y,w,h))

    z, x_bl, x_ur, y_bl, y_ur = int(sliceno), x - w, x + w, y - h, y + h
    print(z, x_bl, x_ur, y_bl, y_ur)

    slice_start = np.max([0, wide_patch_pos[0] - np.int(patch_size[0] / 2.0)])
    slice_end = np.min([wide_patch_pos[0] + np.int(patch_size[0] / 2.0), 165])

    print("Slice start, slice end {} {}".format(slice_start, slice_end))
    out_of_bounds_w = np.hstack(
        (
            np.where(orig_click_data[:, 1] >= x_ur)[0],
            np.where(orig_click_data[:, 1] <= x_bl)[0],
            np.where(orig_click_data[:, 2] >= y_ur)[0],
            np.where(orig_click_data[:, 2] < y_bl)[0],
            np.where(orig_click_data[:, 0] <= slice_start)[0],
            np.where(orig_click_data[:, 0] >= slice_end)[0],
        )
    )

    click_data_w = np.delete(orig_click_data, out_of_bounds_w, axis=0)

    click_data_wide_arr = np.array(click_data_w)
    print("Click_data_wide_arr shape: {}".format(click_data_wide_arr.shape))

    # click_data_wide_arr[:,0] = click_data_wide_arr[:,0] - x_bl
    # click_data_wide_arr[:,1] = click_data_wide_arr[:,0] - y_bl
    print("Length of original click_data {}".format(orig_click_data.shape[0]))
    print(
        "Length after deleting out of bounds clicks: {}".format(
            click_data_wide_arr.shape[0]
        )
    )

    sel_wide_clicks, x_coords_range, y_coords_range = generate_clicklist(
        click_data_wide_arr, crop_roi, slice_start, slice_end
    )

    if z_depth > 1:
        img = get_vol_in_bbox(
            img_data, slice_start, slice_end, int(np.ceil(y)), int(np.ceil(x)), h, w
        )
    else:
        img = get_img_in_bbox(img_data, sliceno, int(np.ceil(x)), int(np.ceil(y)), w, h)

    y_str = "{:10.4f}".format(y)
    x_str = "{:10.4f}".format(x)

    img_titles.append(x_str + " " + y_str + "\n " + "Slice no: " + str(sliceno))

    return img, img_titles, click_data_wide_arr


def generate_full_resized_click_plot_data(
    img_data, click_coords, patch_size=(PATCH_DIM, PATCH_DIM)
):
    img_shortlist = []
    img_titles = []
    img_coords = []
    for j in range(len(click_coords)):
        sliceno, y, x = click_coords[j]
        w, h = patch_size
        w += 10
        h += 10
        # print(x,y,w,h,sliceno)
        img_coords.append((sliceno, x, y, w, h))

        img = get_img_in_bbox(img_data, sliceno, int(np.ceil(x)), int(np.ceil(y)), w, h)
        img = resize(img, (28, 28))

        img_shortlist.append(img)
        # y_str = "{:.3f}".format(y)
        # x_str = "{:.3f}".format(x)
        img_titles.append(str(int(x)) + "_" + str(int(y)) + "_" + str(int(sliceno)))

    return img_shortlist, img_titles, img_coords


def get_single_class(
    class_string="DLP Full",
    window_sel=(0, 500),
    batch_size=32,
    offset=0,
    plot_all=False,
    plot_titles=True,
    patch_size=(PATCH_DIM, PATCH_DIM),
):

    zoon_singleclass_df = zoon_anno_df.loc[
        zoon_anno_df["class_str"].isin([class_string])
    ]

    img_coords_df = zoon_singleclass_df[
        ["z", "x", "y", "class_code", "class_str", "xstart", "xend", "ystart", "yend"]
    ]
    img_coords_df["w"] = patch_size[0]
    img_coords_df["h"] = patch_size[1]

    img_coords_df = img_coords_df.iloc[window_sel[0] : window_sel[1]]
    # img_coords = img_coords.values

    singleclass_click_data = img_coords_df[["z", "x", "y"]]
    # singleclass_click_data=singleclass_click_data.iloc[window_sel[0]:window_sel[1]]
    print(singleclass_click_data.shape)

    p2_click_data_sel = np.array(singleclass_click_data.values).astype(np.float32)

    print(f"Selected single class data of shape {p2_click_data_sel.shape}")

    sel_clicks, x_coords_range, y_coords_range = generate_clicklist(
        p2_click_data_sel, crop_roi, 0, 165
    )

    print(f"Length of original click_data {sel_clicks.shape[0]})")

    vol_x_max = vol_shape_x - ((PATCH_DIM + 1) * 2)
    vol_x_min = (PATCH_DIM + 1) * 2

    vol_y_max = vol_shape_y - ((PATCH_DIM + 1) * 2)
    vol_y_min = (PATCH_DIM + 1) * 2

    vol_z_max = vol_shape_z - 20
    vol_z_min = 20

    print(vol_x_max, vol_x_min, vol_y_max, vol_y_min, vol_z_max, vol_z_min)

    out_of_bounds = np.hstack(
        (
            np.where(sel_clicks[:, 1] >= vol_x_max)[0],
            np.where(sel_clicks[:, 1] <= vol_x_min)[0],
            np.where(sel_clicks[:, 2] >= vol_y_max)[0],
            np.where(sel_clicks[:, 2] <= vol_y_min)[0],
            np.where(sel_clicks[:, 0] >= vol_z_max)[0],
            np.where(sel_clicks[:, 0] <= vol_z_min)[0],
        )
    )

    sel_clicks = np.delete(sel_clicks, out_of_bounds, axis=0)

    print("Length after deleting out of bounds clicks: {}".format(sel_clicks.shape[0]))

    win_start = window_sel[0]  # batch_size * offset
    win_end = window_sel[1]  # win_start + batch_size + 1

    prepared_images, img_titles, img_coords = generate_stacked_click_plot_data(
        (wf1, wf2), sel_clicks[win_start:win_end], patch_size=patch_size, resize=True
    )
    prepared_titles = [str(class_string) + "_" + img_title for img_title in img_titles]

    # img_class_str = np.array([class_string] * len(img_coords))
    # print(prepared_images[0])

    print("Length of image shortlist: {}".format(len(img_shortlist)))
    print(len(sel_clicks), x_coords_range, y_coords_range)
    print(vol_shape_x, vol_shape_y, vol_shape_z)

    grid_side_dim = np.int(math.sqrt(batch_size))
    print("Grid side dim: {}".format(grid_side_dim))

    if not plot_titles:
        img_titles = [0] * len(img_titles)

    # if plot_all:
    # plt.title(class_string)
    #   grid_of_images(selected_images[win_start:win_end], grid_side_dim,
    #                      grid_side_dim,  image_titles=img_titles)
    #
    return np.array(prepared_images), np.array(prepared_titles), np.array(img_coords_df)