# Licensed under a 3-clause BSD style license - see LICENSE.rst

from __future__ import (print_function, division, absolute_import,
                        unicode_literals)

import os
from shutil import rmtree
from tempfile import mkdtemp
from glob import iglob
import sys
import logging
import pytest

import astropy.io.fits as fits
import numpy as np

from astropy.tests.helper import catch_warnings
from astropy.utils import minversion
from astropy.utils.exceptions import AstropyUserWarning
from astropy.extern import six

from astropy.nddata import CCDData

from ..image_collection import ImageFileCollection

_filters = []
_original_dir = ''

_ASTROPY_LT_1_3 = not minversion("astropy", "1.3")


def test_fits_summary(triage_setup):
    keywords = ['imagetyp', 'filter']
    ic = ImageFileCollection(triage_setup.test_dir,
                             keywords=keywords)
    summary = ic._fits_summary(header_keywords=keywords)
    assert len(summary['file']) == triage_setup.n_test['files']
    for keyword in keywords:
        assert len(summary[keyword]) == triage_setup.n_test['files']
    # explicit conversion to array is needed to avoid astropy Table bug in
    # 0.2.4
    no_filter_no_object_row = np.array(summary['file'] ==
                                       'no_filter_no_object_bias.fit')
    # there should be no filter keyword in the bias file
    assert summary['filter'][no_filter_no_object_row].mask


class TestImageFileCollectionRepresentation(object):
    def test_repr_location(self, triage_setup):
        ic = ImageFileCollection(location=triage_setup.test_dir)
        assert repr(ic) == "ImageFileCollection(location={0!r})".format(
            triage_setup.test_dir)

    def test_repr_keywords(self, triage_setup):
        ic = ImageFileCollection(
            location=triage_setup.test_dir, keywords=['imagetyp'])
        ref = ("ImageFileCollection(location={0!r}, keywords=['imagetyp'])"
               .format(triage_setup.test_dir))
        assert repr(ic) == ref

    def test_repr_globs(self, triage_setup):
        ic = ImageFileCollection(
            location=triage_setup.test_dir, glob_exclude="*no_filter*",
            glob_include="*object_light*")
        ref = ("ImageFileCollection(location={0!r}, "
               "glob_include='*object_light*', "
               "glob_exclude='*no_filter*')"
               .format(triage_setup.test_dir))
        assert repr(ic) == ref

    def test_repr_files(self, triage_setup):
        ic = ImageFileCollection(
            location=triage_setup.test_dir,
            filenames=['no_filter_no_object_light.fit',
                       'no_filter_no_object_bias.fit'])
        ref = ("ImageFileCollection(location={0!r}, "
               "filenames=[{1}'no_filter_no_object_light.fit', "
               "{1}'no_filter_no_object_bias.fit'])"
               .format(triage_setup.test_dir, 'u' if six.PY2 else ''))
        assert repr(ic) == ref

    def test_repr_ext(self, triage_setup):

        hdul = fits.HDUList([fits.PrimaryHDU(np.ones((10, 10))),
                             fits.ImageHDU(np.ones((10, 10)))])
        hdul.writeto(os.path.join(triage_setup.test_dir, 'mef.fits'))

        ic = ImageFileCollection(
            location=triage_setup.test_dir,
            filenames=['mef.fits'],
            ext=1)
        ref = ("ImageFileCollection(location={0!r}, "
               "filenames=[{1}'mef.fits'], "
               "ext=1)"
               .format(triage_setup.test_dir, 'u' if six.PY2 else ''))
        assert repr(ic) == ref

    def test_repr_info(self, triage_setup):
        summary_file_path = os.path.join(triage_setup.test_dir, 'info.csv')
        ic = ImageFileCollection(
            location=triage_setup.test_dir, keywords=['naxis'])
        ic.summary.write(summary_file_path)
        with catch_warnings() as w:
            ic2 = ImageFileCollection(info_file=summary_file_path)
        # ImageFileCollections from info_files contain no files. That issues
        # a Warning that we'll ignore here.
        assert len(w) == 2
        assert "'info_file' argument is deprecated" in str(w[0].message)
        assert 'no FITS files in the collection' in str(w[1].message)

        ref = ("ImageFileCollection(keywords=['naxis'], info_file={0!r})"
               .format(summary_file_path))
        assert repr(ic2) == ref


# This should work mark all test methods as using the triage_setup
# fixture, but it doesn't, so the fixture is given explicitly as an
# argument to each method.
# @pytest.mark.usefixtures("triage_setup")
class TestImageFileCollection(object):
    def _setup_logger(self, path, level=logging.WARN):
        """
        Set up file logger at the path.
        """
        logger = logging.getLogger()
        logger.setLevel(level)
        logger.addHandler(logging.FileHandler(path))
        return logger

    def test_filter_files(self, triage_setup):
        img_collection = ImageFileCollection(
            location=triage_setup.test_dir, keywords=['imagetyp', 'filter'])
        assert len(img_collection.files_filtered(
            imagetyp='bias')) == triage_setup.n_test['bias']
        assert len(img_collection.files) == triage_setup.n_test['files']
        assert ('filter' in img_collection.keywords)
        assert ('flying monkeys' not in img_collection.keywords)
        assert len(img_collection.values('imagetyp', unique=True)) == 2

    def test_filter_files_whitespace_keys(self, triage_setup):
        hdr = fits.Header([('HIERARCH a b', 2)])
        hdul = fits.HDUList([fits.PrimaryHDU(np.ones((10, 10)), header=hdr)])
        hdul.writeto(os.path.join(triage_setup.test_dir,
                                  'hdr_with_whitespace.fits'))

        ic = ImageFileCollection(location=triage_setup.test_dir)
        # Using a dictionary and unpacking it should work
        filtered = ic.files_filtered(**{'a b': 2})
        assert len(filtered) == 1
        assert 'hdr_with_whitespace.fits' in filtered

        # Also check it's working with generators:
        for _, filename in ic.data(a_b=2, replace_='_',
                                   return_fname=True):
            assert filename == 'hdr_with_whitespace.fits'

    def test_filter_files_with_str_on_nonstr_column(self, triage_setup):
        ic = ImageFileCollection(location=triage_setup.test_dir)
        # Filtering an integer column with a string
        filtered = ic.files_filtered(naxis='2')
        assert len(filtered) == 0

    def test_filtered_files_have_proper_path(self, triage_setup):
        ic = ImageFileCollection(location=triage_setup.test_dir, keywords='*')
        # Get a subset of the files.
        plain_biases = ic.files_filtered(imagetyp='bias')
        # Force a copy...
        plain_biases = list(plain_biases)
        # Same subset, but with full path.
        path_biases = ic.files_filtered(imagetyp='bias', include_path=True)
        for path_b, plain_b in zip(path_biases, plain_biases):
            # If the path munging has been done properly, this will succeed.
            assert os.path.basename(path_b) == plain_b

    def test_filenames_are_set_properly(self, triage_setup):
        fn = ['filter_no_object_bias.fit', 'filter_object_light_foo.fit']
        img_collection = ImageFileCollection(
            location=triage_setup.test_dir, filenames=fn, keywords=['filter'])
        assert img_collection.files == fn

        img_collection.refresh()
        assert img_collection.files == fn

        fn = 'filter_no_object_bias.fit'
        img_collection = ImageFileCollection(
            location=triage_setup.test_dir, filenames=fn, keywords=['filter'])
        assert img_collection.files == [fn]

    def test_keywords_deleter(self, triage_setup):
        ic = ImageFileCollection(triage_setup.test_dir, keywords='*')

        assert ic.keywords != []
        del ic.keywords
        assert ic.keywords == []

    def test_files_with_compressed(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir)
        assert len(collection._fits_files_in_directory(
            compressed=True)) == triage_setup.n_test['files']

    def test_files_with_no_compressed(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir)
        n_files_found = len(
            collection._fits_files_in_directory(compressed=False))
        n_uncompressed = (triage_setup.n_test['files'] -
                          triage_setup.n_test['compressed'])
        assert n_files_found == n_uncompressed

    def test_generator_full_path(self, triage_setup):
        collection = ImageFileCollection(
            location=triage_setup.test_dir, keywords=['imagetyp'])

        for path, file_name in zip(collection._paths(), collection.files):
            assert path == os.path.join(triage_setup.test_dir, file_name)

    def test_hdus(self, triage_setup):
        collection = ImageFileCollection(
            location=triage_setup.test_dir, keywords=['imagetyp'])

        n_hdus = 0
        for hdu in collection.hdus():
            assert isinstance(hdu, fits.PrimaryHDU)
            data = hdu.data  # must access the data to force scaling
            # pre-astropy 1.1 unsigned data was changed to float32 and BZERO
            # removed. In 1.1 and later, BZERO stays but the data type is
            # unsigned int.
            assert (('BZERO' not in hdu.header) or
                    (data.dtype is np.dtype(np.uint16)))
            n_hdus += 1
        assert n_hdus == triage_setup.n_test['files']

    def test_hdus_masking(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp', 'exposure'])
        old_data = np.array(collection.summary)
        for hdu in collection.hdus(imagetyp='bias'):
            pass
        new_data = np.array(collection.summary)
        assert (new_data == old_data).all()

    @pytest.mark.parametrize('extension', ['TESTEXT', 1, ('TESTEXT', 1)])
    def test_multiple_extensions(self, triage_setup, extension):
        ext1 = fits.PrimaryHDU()
        ext1.data = np.arange(1, 5)
        # It is important than the name used for this test extension
        # NOT be MASK or UNCERT because both are treated in a special
        # way by the FITS reader.
        test_ext_name = 'TESTEXT'
        ext2 = fits.ImageHDU(name=test_ext_name)
        ext2.data = np.arange(6, 10)
        hdulist = fits.hdu.hdulist.HDUList([ext1, ext2])

        hdulist.writeto(os.path.join(triage_setup.test_dir,
                                     'multi-extension.fits'))
        ic2 = ImageFileCollection(
            triage_setup.test_dir, keywords='*',
            filenames=['multi-extension.fits'], ext=extension)

        ic1 = ImageFileCollection(
            triage_setup.test_dir,
            keywords='*', filenames=['multi-extension.fits'], ext=0)

        assert ic1.ext == 0
        assert ic2.ext == extension

        column2 = ic2.summary.colnames
        column1 = ic1.summary.colnames

        assert column1 != column2

        list1 = [key.lower() for key in ext2.header]
        list2 = ic2.summary.colnames[1:]

        assert list1 == list2

        ccd_kwargs = {'unit': 'adu'}
        for data, hdr, hdu, ccd in zip(ic2.data(),
                                       ic2.headers(),
                                       ic2.hdus(),
                                       ic2.ccds(ccd_kwargs)):
            np.testing.assert_array_equal(data, ext2.data)
            assert hdr == ext2.header
            # Now compare that the generators each give the same stuff
            np.testing.assert_array_equal(data, ccd.data)
            np.testing.assert_array_equal(data, hdu.data)
            assert hdr == hdu.header
            assert hdr == ccd.meta

    def test_headers(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp'])
        n_headers = 0
        for header in collection.headers():
            assert isinstance(header, fits.Header)
            assert ('bzero' in header)
            n_headers += 1
        assert n_headers == triage_setup.n_test['files']

    def test_headers_save_location(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp'])
        destination = mkdtemp()
        for header in collection.headers(save_location=destination):
            pass
        new_collection = ImageFileCollection(location=destination,
                                             keywords=['imagetyp'])
        basenames = lambda paths: set(
            [os.path.basename(file) for file in paths])

        assert (len(basenames(collection._paths()) -
                    basenames(new_collection._paths())) == 0)
        rmtree(destination)

    def test_headers_with_filter(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp'])
        cnt = 0
        for header in collection.headers(imagetyp='light'):
            assert header['imagetyp'].lower() == 'light'
            cnt += 1
        assert cnt == triage_setup.n_test['light']

    def test_headers_with_multiple_filters(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp'])
        cnt = 0
        for header in collection.headers(imagetyp='light',
                                         filter='R'):
            assert header['imagetyp'].lower() == 'light'
            assert header['filter'].lower() == 'r'
            cnt += 1
        assert cnt == (triage_setup.n_test['light'] -
                       triage_setup.n_test['need_filter'])

    def test_headers_with_filter_wildcard(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp'])
        cnt = 0
        for header in collection.headers(imagetyp='*'):
            cnt += 1
        assert cnt == triage_setup.n_test['files']

    def test_headers_with_filter_missing_keyword(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp'])
        for header in collection.headers(imagetyp='light',
                                         object=''):
            assert header['imagetyp'].lower() == 'light'
            with pytest.raises(KeyError):
                header['object']

    def test_generator_headers_save_with_name(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp'])
        for header in collection.headers(save_with_name='_new'):
            assert isinstance(header, fits.Header)
        new_collection = ImageFileCollection(location=triage_setup.test_dir,
                                             keywords=['imagetyp'])
        assert (len(new_collection._paths()) ==
                2 * (triage_setup.n_test['files']) -
                triage_setup.n_test['compressed'])
        [os.remove(fil) for fil in iglob(triage_setup.test_dir + '/*_new*')]

    def test_generator_data(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp'])
        for img in collection.data():
            assert isinstance(img, np.ndarray)

    def test_generator_ccds_without_unit(self, triage_setup):
        collection = ImageFileCollection(
                location=triage_setup.test_dir, keywords=['imagetyp'])

        with pytest.raises(ValueError):
            ccd = next(collection.ccds())

    def test_generator_ccds(self, triage_setup):
        collection = ImageFileCollection(
                location=triage_setup.test_dir, keywords=['imagetyp'])
        ccd_kwargs = {'unit': 'adu'}
        for ccd in collection.ccds(ccd_kwargs=ccd_kwargs):
            assert isinstance(ccd, CCDData)

    def test_consecutive_fiilters(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp', 'filter',
                                                   'object'])
        no_files_match = collection.files_filtered(object='fdsafs')
        assert(len(no_files_match) == 0)
        some_files_should_match = collection.files_filtered(object=None,
                                                            imagetyp='light')
        assert(len(some_files_should_match) ==
               triage_setup.n_test['need_object'])

    def test_filter_does_not_not_permanently_change_file_mask(self,
                                                              triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp'])
        # ensure all files are originally unmasked
        assert not collection.summary['file'].mask.any()
        # generate list that will match NO files
        collection.files_filtered(imagetyp='foisajfoisaj')
        # if the code works, this should have no permanent effect
        assert not collection.summary['file'].mask.any()

    @pytest.mark.parametrize("new_keywords,collection_keys", [
                            (['imagetyp', 'object'], ['imagetyp', 'filter']),
                            (['imagetyp'], ['imagetyp', 'filter'])])
    def test_keyword_setting(self, new_keywords, collection_keys,
                             triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=collection_keys)
        tbl_orig = collection.summary
        collection.keywords = new_keywords
        tbl_new = collection.summary

        if set(new_keywords).issubset(collection_keys):
            # should just delete columns without rebuilding table
            assert(tbl_orig is tbl_new)
        else:
            # we need new keywords so must rebuild
            assert(tbl_orig is not tbl_new)

        for key in new_keywords:
            assert(key in tbl_new.keys())
        assert (tbl_orig['file'] == tbl_new['file']).all()
        assert (tbl_orig['imagetyp'] == tbl_new['imagetyp']).all()
        assert 'filter' not in tbl_new.keys()
        assert 'object' not in tbl_orig.keys()

    def test_keyword_setting_to_empty_list(self, triage_setup):
        ic = ImageFileCollection(triage_setup.test_dir)
        ic.keywords = []
        assert ['file'] == ic.keywords

    def test_header_and_filename(self, triage_setup):
        collection = ImageFileCollection(location=triage_setup.test_dir,
                                         keywords=['imagetyp'])
        for header, fname in collection.headers(return_fname=True):
            assert (fname in collection.summary['file'])
            assert (isinstance(header, fits.Header))

    def test_dir_with_no_fits_files(self, tmpdir):
        empty_dir = tmpdir.mkdtemp()
        some_file = empty_dir.join('some_file.txt')
        some_file.dump('words')
        with catch_warnings() as w:
            collection = ImageFileCollection(location=empty_dir.strpath,
                                             keywords=['imagetyp'])
        assert len(w) == 1
        assert str(w[0].message) == "no FITS files in the collection."
        assert collection.summary is None
        for hdr in collection.headers():
            # this statement should not be reached if there are no FITS files
            assert 0

    def test_dir_with_no_keys(self, tmpdir):
        # This test should fail if the FITS files in the directory
        # are actually read.
        bad_dir = tmpdir.mkdtemp()
        not_really_fits = bad_dir.join('not_fits.fit')
        not_really_fits.dump('I am not really a FITS file')
        # make sure an error will be generated if the FITS file is read
        with pytest.raises(IOError):
            fits.getheader(not_really_fits.strpath)

        log = tmpdir.join('tmp.log')
        self._setup_logger(log.strpath)

        _ = ImageFileCollection(location=bad_dir.strpath, keywords=[])

        with open(log.strpath) as f:
            warnings = f.read()

        # ImageFileCollection will suppress the IOError but log a warning
        # so check that the log has no warnings in it.
        assert (len(warnings) == 0)

    def test_fits_summary_when_keywords_are_not_subset(self, triage_setup):
        """
        Catch case when there is overlap between keyword list
        passed to the ImageFileCollection and to files_filtered
        but the latter is not a subset of the former.
        """
        ic = ImageFileCollection(triage_setup.test_dir,
                                 keywords=['imagetyp', 'exptime'])
        n_files = len(ic.files)
        files_missing_this_key = ic.files_filtered(imagetyp='*',
                                                   monkeys=None)
        assert(n_files > 0)
        assert(n_files == len(files_missing_this_key))

    def test_duplicate_keywords_in_setting(self, triage_setup):
        keywords_in = ['imagetyp', 'a', 'a']
        ic = ImageFileCollection(triage_setup.test_dir,
                                 keywords=keywords_in)
        for key in set(keywords_in):
            assert (key in ic.keywords)
        # one keyword gets added: file
        assert len(ic.keywords) < len(keywords_in) + 1

    def test_keyword_includes_file(self, triage_setup):
        keywords_in = ['file', 'imagetyp']
        ic = ImageFileCollection(triage_setup.test_dir,
                                 keywords=keywords_in)
        assert 'file' in ic.keywords
        file_keywords = [key for key in ic.keywords if key == 'file']
        assert len(file_keywords) == 1

    def test_setting_keywords_to_none(self, triage_setup):
        ic = ImageFileCollection(triage_setup.test_dir, keywords=['imagetyp'])
        ic.keywords = None
        assert ic.summary == []

    def test_getting_value_for_keyword(self, triage_setup):
        ic = ImageFileCollection(triage_setup.test_dir, keywords=['imagetyp'])
        # Does it fail if the keyword is not in the summary?
        with pytest.raises(ValueError):
            ic.values('filter')
        # If I ask for unique values do I get them?
        values = ic.values('imagetyp', unique=True)

        assert values == list(set(ic.summary['imagetyp']))
        assert len(values) < len(ic.summary['imagetyp'])
        # Does the list of non-unique values match the raw column?
        values = ic.values('imagetyp', unique=False)
        assert values == list(ic.summary['imagetyp'])
        # Does unique actually default to false?
        values2 = ic.values('imagetyp')
        assert values == values2

    def test_collection_when_one_file_not_fits(self, triage_setup):
        not_fits = 'foo.fit'
        path_bad = os.path.join(triage_setup.test_dir, not_fits)
        # create an empty file...
        with open(path_bad, 'w'):
            pass
        ic = ImageFileCollection(triage_setup.test_dir, keywords=['imagetyp'])
        assert not_fits not in ic.summary['file']
        os.remove(path_bad)

    def test_data_type_mismatch_in_fits_keyword_values(self, triage_setup):
        # If one keyword has an unexpected type, do we notice?
        img = np.uint16(np.arange(100))
        bad_filter = fits.PrimaryHDU(img)
        bad_filter.header['imagetyp'] = 'LIGHT'
        bad_filter.header['filter'] = 15.0
        path_bad = os.path.join(triage_setup.test_dir, 'bad_filter.fit')
        bad_filter.writeto(path_bad)
        ic = ImageFileCollection(triage_setup.test_dir, keywords=['filter'])
        # dtype is object when there is a mix of types
        assert ic.summary['filter'].dtype == np.dtype('O')
        os.remove(path_bad)

    def test_filter_by_numerical_value(self, triage_setup):
        ic = ImageFileCollection(triage_setup.test_dir, keywords=['naxis'])
        should_be_zero = ic.files_filtered(naxis=2)
        assert len(should_be_zero) == 0
        should_not_be_zero = ic.files_filtered(naxis=1)
        assert len(should_not_be_zero) == triage_setup.n_test['files']

    def test_files_filtered_with_full_path(self, triage_setup):
        ic = ImageFileCollection(triage_setup.test_dir, keywords=['naxis'])
        files = ic.files_filtered(naxis=1, include_path=True)

        for f in files:
            assert f.startswith(triage_setup.test_dir)

    def test_unknown_generator_type_raises_error(self, triage_setup):
        ic = ImageFileCollection(triage_setup.test_dir, keywords=['naxis'])
        with pytest.raises(ValueError):
            for foo in ic._generator('not a real generator'):
                pass

    def test_setting_write_location_to_bad_dest_raises_error(self, tmpdir,
                                                             triage_setup):
        new_tmp = tmpdir.mkdtemp()
        bad_directory = new_tmp.join('foo')

        ic = ImageFileCollection(triage_setup.test_dir, keywords=['naxis'])
        with pytest.raises(IOError):
            for hdr in ic.headers(save_location=bad_directory.strpath):
                pass

    def test_initializing_from_table(self, triage_setup):
        keys = ['imagetyp', 'filter']
        ic = ImageFileCollection(triage_setup.test_dir, keywords=keys)
        table = ic.summary
        table_path = os.path.join(triage_setup.test_dir, 'input_tbl.csv')
        nonsense = 'forks'
        table['imagetyp'][0] = nonsense
        table.write(table_path, format='ascii', delimiter=',')
        with catch_warnings() as w:
            ic = ImageFileCollection(location=None, info_file=table_path)
        # By using location=None we don't have actual files in the collection.
        assert len(w) == 2
        assert "'info_file' argument is deprecated" in str(w[0].message)
        assert str(w[1].message) == "no FITS files in the collection."

        # keywords can only have been set from saved table
        for key in keys:
            assert key in ic.keywords
        # no location, so should be no files
        assert len(ic.files) == 0
        # no location, so no way to iterate over files
        with pytest.raises((AttributeError, TypeError)):
            for h in ic.headers():
                pass
        with catch_warnings() as w:
            ic = ImageFileCollection(location=triage_setup.test_dir,
                                     info_file=table_path)
        assert len(w) == 1
        assert "'info_file' argument is deprecated" in str(w[0].message)
        # we now have a location, so did we get files?
        assert len(ic.files) == len(table)
        # Is the summary table masked?
        assert ic.summary.masked
        # can I loop over headers?
        for h in ic.headers():
            assert isinstance(h, fits.Header)
        # Does ImageFileCollection summary contain values from table?
        assert nonsense in ic.summary['imagetyp']

    def test_initializing_from_table_file_that_does_not_exist(
            self, triage_setup, tmpdir):
        log = tmpdir.join('tmp.log')

        self._setup_logger(log.strpath)

        # Do we get a warning if we try reading a file that doesn't exist,
        # but where we can initialize from a directory?
        with catch_warnings() as w:
            ic = ImageFileCollection(
                location=triage_setup.test_dir,
                info_file='iufadsdhfasdifre')
        assert len(w) == 1
        assert "'info_file' argument is deprecated" in str(w[0].message)

        with open(log.strpath) as f:
            warnings = f.readlines()

        assert (len(warnings) == 1)
        is_in = ['unable to open table file' in w for w in warnings]
        assert all(is_in)
        # Do we raise an error if the table name is bad AND the location
        # is None?
        with pytest.raises(IOError):
            # Because the location is None we get a Warning about "no files in
            # the collection".
            with catch_warnings() as w:
                ImageFileCollection(location=None, info_file='iufadsdhfasdifre')
        assert len(w) == 2
        assert "'info_file' argument is deprecated" in str(w[0].message)
        assert str(w[1].message) == "no FITS files in the collection."

        # Do we raise an error if the table name is bad AND
        # the location is given but is bad?
        with pytest.raises(OSError):
            with catch_warnings() as w:
                ic = ImageFileCollection(location='dasifjoaurun',
                                         info_file='iufadsdhfasdifre')
        assert len(w) == 1
        assert "'info_file' argument is deprecated" in str(w[0].message)

    def test_no_fits_files_in_collection(self):
        with catch_warnings(AstropyUserWarning) as warning_lines:
            # FIXME: What exactly does this assert?
            assert "no fits files in the collection."

    def test_initialization_with_no_keywords(self, triage_setup):
        # This test is primarily historical -- the old default for
        # keywords was an empty list (it is now the wildcard '*').
        ic = ImageFileCollection(location=triage_setup.test_dir, keywords=[])
        # iteration below failed before bugfix...
        execs = 0
        for h in ic.headers():
            execs += 1
        assert not execs

    def check_all_keywords_in_collection(self, image_collection):
        lower_case_columns = [c.lower() for c in
                              image_collection.summary.colnames]
        for h in image_collection.headers():
            for k in h:
                assert k.lower() in lower_case_columns

    def test_tabulate_all_keywords(self, triage_setup):
        ic = ImageFileCollection(location=triage_setup.test_dir, keywords='*')
        self.check_all_keywords_in_collection(ic)

    def test_summary_table_is_always_masked(self, triage_setup):
        # First, try grabbing all of the keywords
        ic = ImageFileCollection(location=triage_setup.test_dir, keywords='*')
        assert ic.summary.masked
        # Now, try keywords that every file will have
        ic.keywords = ['bitpix']
        assert ic.summary.masked
        # What about keywords that include some that will surely be missing?
        ic.keywords = ['bitpix', 'dsafui']
        assert ic.summary.masked

    def test_case_of_keywords_respected(self, triage_setup):
        keywords_in = ['BitPix', 'instrume', 'NAXIS']
        ic = ImageFileCollection(location=triage_setup.test_dir,
                                 keywords=keywords_in)
        for key in keywords_in:
            assert key in ic.summary.colnames

    def test_grabbing_all_keywords_and_specific_keywords(self, triage_setup):
        keyword_not_in_headers = 'OIdn89!@'
        ic = ImageFileCollection(triage_setup.test_dir,
                                 keywords=['*', keyword_not_in_headers])
        assert keyword_not_in_headers in ic.summary.colnames
        self.check_all_keywords_in_collection(ic)

    def test_grabbing_all_keywords_excludes_empty_key(self, triage_setup):
        # This test needs a file with a blank keyword in it to ensure
        # that case is handled correctly.
        blank_keyword = fits.PrimaryHDU()
        blank_keyword.data = np.zeros((100, 100))
        blank_keyword.header[''] = 'blank'

        blank_keyword.writeto(os.path.join(triage_setup.test_dir,
                                           'blank.fits'))

        ic = ImageFileCollection(triage_setup.test_dir, keywords='*')
        assert 'col0' not in ic.summary.colnames

    def test_header_with_long_history_roundtrips_to_disk(self, triage_setup):
        # I tried combing several history comments into one table entry with
        # '\n'.join(history), which resulted in a table that couldn't
        # round trip to disk because on read the newline character was
        # interpreted as...a new line! This test is a check against future
        # foolishness.
        from astropy.table import Table
        img = np.uint16(np.arange(100))
        long_history = fits.PrimaryHDU(img)
        long_history.header['imagetyp'] = 'BIAS'
        long_history.header['history'] = 'Something happened'
        long_history.header['history'] = 'Then something else happened'
        long_history.header['history'] = 'And then something odd happened'
        path_history = os.path.join(triage_setup.test_dir, 'long_history.fit')
        long_history.writeto(path_history)
        ic = ImageFileCollection(triage_setup.test_dir, keywords='*')
        ic.summary.write('test_table.txt', format='ascii.csv')
        table_disk = Table.read('test_table.txt', format='ascii.csv')
        assert len(table_disk) == len(ic.summary)

    @pytest.mark.skipif("os.environ.get('APPVEYOR') or os.sys.platform == 'win32'",
                        reason="fails on Windows because file "
                               "overwriting fails")
    def test_refresh_method_sees_added_keywords(self, triage_setup):
        ic = ImageFileCollection(triage_setup.test_dir, keywords='*')
        # Add a keyword I know isn't already in the header to each file.
        not_in_header = 'BARKARK'

        for h in ic.headers(overwrite=True):
            h[not_in_header] = True

        assert not_in_header not in ic.summary.colnames

        ic.refresh()
        # After refreshing the odd keyword should be present.
        assert not_in_header.lower() in ic.summary.colnames

    def test_refresh_method_sees_added_files(self, triage_setup):
        ic = ImageFileCollection(triage_setup.test_dir, keywords='*')
        # Compressed files don't get copied. Not sure why...
        original_len = len(ic.summary) - triage_setup.n_test['compressed']
        # Generate additional files in this directory
        for h in ic.headers(save_with_name="_foo"):
            pass
        ic.refresh()
        new_len = len(ic.summary) - triage_setup.n_test['compressed']
        assert new_len == 2 * original_len

    def test_keyword_order_is_preserved(self, triage_setup):
        keywords = ['imagetyp', 'exposure', 'filter']
        ic = ImageFileCollection(triage_setup.test_dir, keywords=keywords)
        assert ic.keywords == ['file'] + keywords

    def test_sorting(self, triage_setup):
        collection = ImageFileCollection(
            location=triage_setup.test_dir,
            keywords=['imagetyp', 'filter', 'object'])

        all_elements = []
        for hdu, fname in collection.hdus(return_fname=True):
            all_elements.append((str(hdu.header), fname))
        # Now sort
        collection.sort(keys=['imagetyp', 'object'])
        # and check it's all still right
        for hdu, fname in collection.hdus(return_fname=True):
            assert((str(hdu.header), fname) in all_elements)
        for i in range(len(collection.summary)):
            assert(collection.summary['file'][i] == collection.files[i])

    @pytest.mark.skipif(
        _ASTROPY_LT_1_3,
        reason="It seems to fail with a TypeError there but because of "
               "different reasons (something to do with NumPy).")
    def test_sorting_without_key_fails(self, triage_setup):
        ic = ImageFileCollection(location=triage_setup.test_dir)
        with pytest.raises(ValueError):
            ic.sort(keys=None)

    def test_duplicate_keywords(self, triage_setup):
        # Make sure duplicated keywords don't make the imagefilecollection
        # fail.
        hdu = fits.PrimaryHDU()
        hdu.data = np.zeros((5, 5))
        hdu.header['stupid'] = 'fun'
        hdu.header.append(('stupid', 'nofun'))

        hdu.writeto(os.path.join(triage_setup.test_dir, 'duplicated.fits'))

        with catch_warnings(UserWarning) as w:
            ic = ImageFileCollection(triage_setup.test_dir, keywords='*')
        assert len(w) == 1
        assert 'stupid' in str(w[0].message)

        assert 'stupid' in ic.summary.colnames
        assert 'fun' in ic.summary['stupid']
        assert 'nofun' not in ic.summary['stupid']

    @pytest.mark.skipif(
        "sys.platform.startswith('win') and six.PY2",
        reason="os.path.samefile isn't available on windows (python < 3.2).")
    def test_ccds_generator_in_different_directory(self, triage_setup, tmpdir):
        """
        Regression test for https://github.com/astropy/ccdproc/issues/421 in
        which the ccds generator fails if the current working directory is
        not the location of the ImageFileCollection.
        """

        coll = ImageFileCollection(triage_setup.test_dir)

        # The temporary directory below should be different that the collection
        # location.
        os.chdir(tmpdir.strpath)

        # Let's make sure it is.
        assert not os.path.samefile(os.getcwd(), coll.location)

        # This generated an IOError before the issue was fixed.
        for _ in coll.ccds(ccd_kwargs={'unit': 'adu'}):
            pass

    def test_ccds_generator_does_not_support_overwrite(self, triage_setup):
        """
        CCDData objects have several attributes that make it hard to
        reliably support overwriting. For example in what extension should
        mask, uncertainty be written?
        Also CCDData doesn't explicitly support in-place operations so it's to
        easy to create a new CCDData object inadvertantly and all modifications
        might be lost.
        """
        ic = ImageFileCollection(triage_setup.test_dir)
        with pytest.raises(NotImplementedError):
            ic.ccds(overwrite=True)
        with pytest.raises(NotImplementedError):
            ic.ccds(clobber=True)

    def test_glob_matching(self, triage_setup):
        # We'll create two files with strange names to test glob
        #   includes / excludes
        one = fits.PrimaryHDU()
        one.data = np.zeros((5, 5))
        one.header[''] = 'whatever'

        one.writeto(os.path.join(triage_setup.test_dir, 'SPAM_stuff.fits'))
        one.writeto(os.path.join(triage_setup.test_dir, 'SPAM_other_stuff.fits'))

        coll = ImageFileCollection(triage_setup.test_dir, glob_include='SPAM*')
        assert len(coll.files) == 2

        coll = ImageFileCollection(triage_setup.test_dir, glob_include='SPAM*',
                                   glob_exclude='*other*')
        assert len(coll.files) == 1

        # the glob attributes are readonly, so setting them raises an Exception.
        with pytest.raises(AttributeError):
            coll.glob_exclude = '*stuff*'
        with pytest.raises(AttributeError):
            coll.glob_include = '*stuff*'
