#!/usr/bin/python3

# smart-image-renamer
#
# Author: Ronak Gandhi (ronak.gandhi@ronakg.com)
# Project Home Page: https://github.com/ronakg/smart-image-renamer
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Smart Image Renamer main module"""

from _version import __version__
from PIL.ExifTags import TAGS
from PIL import Image
import argparse
import itertools
import os
import re
import datetime
from pymediainfo import MediaInfo
from geopy.geocoders import Nominatim
from PIL.ExifTags import GPSTAGS
import time


class NotAnImageFile(Exception):
    """This file is not an Image"""
    pass


class NotAVideoFile(Exception):
    """This file is not a video"""
    pass


class InvalidExifData(Exception):
    """Could not find any EXIF or corrupted EXIF"""
    pass


class NoExifTimeStamp(Exception):
    """Could not find 'DateTimeOriginal' or 'DateTimeDigitized' EXIF timestamp"""
    pass


class InvalidExifTimeStamp(Exception):
    """Could not process EXIF Timestamp, which should be "YYYY:MM:DD HH:MM:SS" """
    pass


def get_cmd_args():
    """Get, process and return command line arguments to the script
    """
    help_description = '''
Smart Image Renamer

Rename your photos in bulk using information stored in EXIF.
'''

    help_epilog = '''
Format string for the file name is defined by a mix of custom text and following tags enclosed in {}:
  YYYY        Year
  MM          Month
  DD          Day
  hh          Hours
  mm          Minutes
  ss          Seconds
  Seq         Sequence number
  Artist      Artist
  Make        Camera Make
  Model       Camera Model
  Height      Height of image in pixels
  Folder      Parent folder of the image file

Examples:
  Format String:          {YYYY}-{MM}-{DD}-{Folder}-{Seq}
  File Name:              2014-05-09-Wedding_Shoot-001.JPEG
                          2014-05-09-Wedding_Shoot-002.JPEG

  Format String:          {YYYY}{DD}{MM}_{Model}_Beach_Shoot_{Seq}
  File Name:              20140429_PENTAX K-x_Beach_Shoot_001.JPEG
                          20140429_PENTAX K-x_Beach_Shoot_002.JPEG
    '''

    parser = argparse.ArgumentParser(description=help_description,
                                     formatter_class=argparse.RawTextHelpFormatter,
                                     epilog=help_epilog)
    parser.add_argument('-f',
                        dest='format',
                        type=str,
                        default='{YYYY}-{MM}-{DD}_{hh}-{mm}-{ss}_{Height}',
                        help='Format of the new file name (default: {YYYY}-{MM}-{DD}_{hh}-{mm}-{ss}_{Height})')
    parser.add_argument('-s',
                        dest='sequence',
                        type=int,
                        default=1,
                        help='Starting sequence number (default: 1)')
    parser.add_argument('-r', dest='recursive', default=False,
                        action='store_true',
                        help='Recursive mode (default: False)')
    parser.add_argument('-i', dest='hidden', default=False,
                        action='store_true', help='Include hidden files (default: False)')
    parser.add_argument('-t', dest='test', default=False, action='store_true',
                        help='Test mode. Don\'t apply changes. (default: False)')
    parser.add_argument('-V', '--version', action='version',
                        version='%(prog)s {}'.format(__version__))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-v", "--verbose", action="store_true")
    group.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument('input', nargs='+',
                        help='Absolute path to file or directory')

    return parser.parse_args()


def get_exif_data(img_file: str) -> dict:
    """Read EXIF data from the image.

    img_file: Absolute path to the image file

    Returns: A dictionary containing EXIF data of the file

    Raises: NotAnImageFile if file is not an image
            InvalidExifData if EXIF can't be processed
            NoExifTimeStamp if EXIF does not contain timestamp
            InvalidExifTimeStamp if EXIF DateTimeOriginal can't be processed
    """
    try:
        img = Image.open(img_file)
    except (OSError, IOError):
        raise NotAnImageFile

    try:
        # Use TAGS module to make EXIF data human readable
        exif_data = {
            TAGS[k]: v
            for k, v in img._getexif().items()
            if k in TAGS
        }
    except AttributeError:
        raise InvalidExifData

    # Add image format to EXIF
    exif_data['ext'] = img.format
    exif_data['Height'] = str(img.height) + 'px'

    # get location as city and country
    try:
        geotags = get_geotagging(img._getexif())
        coords = get_coordinates_new(exif_data['GPSInfo'])
        #print(app.reverse("%s,%s" % coords))
        address = get_address_by_location(
            coords[0], coords[1]).get('address', '')
        # print(address)
        exif_data['City'] = address.get(
            'town', address.get('suburb', 'unknown'))
        exif_data['Country'] = address.get('country', 'unknown')
    except:
        exif_data['City'] = 'unknown'
        exif_data['Country'] = 'unknown'

    # Find out the original timestamp or digitized timestamp from the EXIF
    img_timestamp = (exif_data.get('DateTimeOriginal') or
                     exif_data.get('DateTimeDigitized'))

    if not img_timestamp:
        raise NoExifTimeStamp

    # Extract year, month, day, hours, minutes, seconds from timestamp
    img_timestamp =\
        re.search(r'(?P<YYYY>\d\d\d?\d?):(?P<MM>\d\d?):(?P<DD>\d\d?) '
                  '(?P<hh>\d\d?):(?P<mm>\d\d?):(?P<ss>\d\d?)',
                  img_timestamp.strip())

    if not img_timestamp:
        raise InvalidExifTimeStamp

    try:
        exif_data.update(img_timestamp.groupdict())
    except Exception:
        print("Fatal Error: update of exif_data didn't work!")

    exif_data['YYYY'] = int(exif_data['YYYY'])
    exif_data['MM'] = int(exif_data['MM'])
    exif_data['DD'] = int(exif_data['DD'])
    exif_data['hh'] = int(exif_data['hh'])
    exif_data['mm'] = int(exif_data['mm'])
    exif_data['ss'] = int(exif_data['ss'])

    return exif_data


def get_img_data(img_file: str) -> dict:
    """ Read image data without EXIF

    img_file: Absolute path to the image file

    Returns: A dictionary containing 'height' and the modification timestamp.

    Raises: NotAnImageFile if file is not an image
    """
    try:
        img = Image.open(img_file)
    except (OSError, IOError):
        raise NotAnImageFile

    img_data = dict()

    img_data['ext'] = img.format
    img_data['Height'] = str(img.height) + 'px'

    dt = datetime.datetime.fromtimestamp(os.path.getmtime(img_file))
    img_data['YYYY'] = dt.year
    img_data['MM'] = dt.month
    img_data['DD'] = dt.day
    img_data['hh'] = dt.hour
    img_data['mm'] = dt.minute
    img_data['ss'] = dt.second
    img_data['Artist'] = ''
    img_data['Make'] = ''
    img_data['Model'] = ''
    img_data['City'] = 'unknown'
    img_data['Country'] = 'unknown'

    return img_data


def get_video_data(video_file: str) -> dict:
    """ Uses mediainfo library to read resolution of video

    Raises: NotAVideoFile if file is not a video
    """

    try:
        vid = MediaInfo.parse(video_file)
    except:
        raise NotAVideoFile

    isvideo = False
    for track in vid.tracks:
        if track.track_type == 'Video':
            height = track.height
            isvideo = True
    if not isvideo:
        raise NotAVideoFile

    vid_data = dict()

    vid_data['ext'] = vid.tracks[0].file_extension
    vid_data['Height'] = str(height) + 'px'

    dt = datetime.datetime.fromtimestamp(os.path.getmtime(video_file))
    vid_data['YYYY'] = dt.year
    vid_data['MM'] = dt.month
    vid_data['DD'] = dt.day
    vid_data['hh'] = dt.hour
    vid_data['mm'] = dt.minute
    vid_data['ss'] = dt.second
    vid_data['Artist'] = ''
    vid_data['Make'] = ''
    vid_data['Model'] = ''
    vid_data['City'] = 'unknown'
    vid_data['Country'] = 'unknown'

    return vid_data

# https://developer.here.com/blog/getting-started-with-geocoding-exif-image-metadata-in-python3


def get_geotagging(exif):
    if not exif:
        raise ValueError("No EXIF metadata found")

    geotagging = {}
    for (idx, tag) in TAGS.items():
        if tag == 'GPSInfo':
            if idx not in exif:
                raise ValueError("No EXIF geotagging found")

            for (key, val) in GPSTAGS.items():
                if key in exif[idx]:
                    geotagging[val] = exif[idx][key]

    return geotagging


def get_decimal_from_dms(dms, ref):

    degrees = dms[0]
    minutes = dms[1] / 60.0
    seconds = dms[2] / 3600.0

    if ref in ['S', 'W']:
        degrees = -degrees
        minutes = -minutes
        seconds = -seconds

    return round(degrees + minutes + seconds, 5)


def get_coordinates(geotags):
    lat = get_decimal_from_dms(
        geotags['GPSLatitude'], geotags['GPSLatitudeRef'])

    lon = get_decimal_from_dms(
        geotags['GPSLongitude'], geotags['GPSLongitudeRef'])

    return (lat, lon)


def get_coordinates_new(geoInfo):
    lat = get_decimal_from_dms(
        geoInfo[2], geoInfo[1])

    lon = get_decimal_from_dms(
        geoInfo[4], geoInfo[3])

    return (lat, lon)


def get_address_by_location(latitude, longitude, language="en"):
    """This function returns an address as raw from a location
    will repeat until success"""
    # build coordinates string to pass to reverse() function
    coordinates = f"{latitude}, {longitude}"
    # sleep for a second to respect Usage Policy
    time.sleep(1)
    trials = 0
    try:
        return app.reverse(coordinates, language=language).raw
    except:
        trials += 1
        if trials >= 5:
            raise ValueError("No address found")
        return get_address_by_location(latitude, longitude)


def find_new_name(old_filename: str) -> str:
    """ Adds sequence number and checks if file also exist. Tries until it finds a good number.

    Returns: new filename of file that does not exist
    """

    sep_idx = old_filename.rfind('.')
    base = old_filename[: sep_idx]
    ext = old_filename[sep_idx:]

    seq = 1
    new_name = base + '_' + str(seq) + ext
    while os.path.isfile(new_name):
        seq = seq + 1
        new_name = base + '_' + str(seq) + ext
    return new_name


if __name__ == '__main__':
    skipped_files = []
    args = get_cmd_args()
    app = Nominatim(user_agent="tutorial")

    input_paths = [os.path.abspath(input) for input in args.input]
    input_format = args.format
    verbose = args.verbose
    quiet = args.quiet
    sequence_start = args.sequence
    test_mode = args.test
    recursive = args.recursive
    include_hidden = args.hidden

    # Make sure the month, days, hours, minutes and seconds have 2 digits
    input_format = input_format.replace('{MM}', '{MM:02d}')
    input_format = input_format.replace('{DD}', '{DD:02d}')
    input_format = input_format.replace('{hh}', '{hh:02d}')
    input_format = input_format.replace('{mm}', '{mm:02d}')
    input_format = input_format.replace('{ss}', '{ss:02d}')
    print("Actual format string:", input_format)

    for input_path in input_paths:
        for root, dirs, files in os.walk(input_path):
            # Skip hidden directories unless specified by user
            if not include_hidden and os.path.basename(root).startswith('.'):
                continue

            # Initialize sequence counter
            # Use no of files to determine padding for sequence numbers
            seq = itertools.count(start=sequence_start)
            seq_width = len(str(len(files)))

            print('Processing folder: {}'.format(root))
            for f in sorted(files):
                # Skip hidden files unless specified by user
                if not include_hidden and f.startswith('.'):
                    continue

                old_file_name = os.path.join(root, f)
                try:
                    # Get EXIF data from the image
                    tag_data = get_exif_data(old_file_name)
                except NotAnImageFile:
                    try:
                        tag_data = get_video_data(old_file_name)
                    except NotAVideoFile:
                        tag_data = get_img_data(old_file_name)
                        if not quiet:
                            print('INFO: ' + old_file_name +
                                  ' is neither an image nor a video file!')
                        continue

                    # Generate data to be replaced in user provided format
                new_image_data = tag_data
                new_image_data['Folder'] = os.path.basename(root),
                new_image_data['File'] = os.path.splitext(f)[0],
                new_image_data['Seq'] = '{0:0{1}d}'.format(
                    next(seq), seq_width)

                # Generate new file name according to user provided format
                new_file_name = (
                    input_format + '.{ext}').format(**new_image_data)
                new_file_name_complete = os.path.join(root, new_file_name)

                # file already has correct file name, skip it
                if old_file_name == new_file_name_complete:
                    continue

                # target file name is already there, maybe high-speed shutter
                # was used (5 pics per second)
                # add a sequence number, so manual comparison is simplified
                if os.path.isfile(new_file_name_complete):
                    new_file_name_complete = find_new_name(
                        new_file_name_complete)
                    if os.path.isfile(new_file_name_complete):
                        print('ERROR: Something went terribly wrong...')

                # Don't rename files if we are running in test mode
                if not test_mode:
                    try:
                        os.rename(old_file_name, new_file_name_complete)
                    except OSError:
                        skipped_files.append((old_file_name,
                                              'Failed to rename file'))
                        continue

                if verbose:
                    print('{0} --> {1}'.format(old_file_name,
                                               new_file_name_complete))
                elif not quiet:
                    print('{0} --> {1}'.format(f, new_file_name))

            # Folder processed
            print('')

            # Break if recursive flag is not present
            if not recursive:
                break
