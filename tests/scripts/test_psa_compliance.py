#!/usr/bin/env python3
"""Run the PSA Crypto API compliance test suite.
Clone the repo and check out the commit specified by PSA_ARCH_TEST_REPO and PSA_ARCH_TEST_REF,
then compile and run the test suite. The clone is stored at <repository root>/psa-arch-tests.
Known defects in either the test suite or mbedtls / psa-crypto - identified by their test
number - are ignored, while unexpected failures AND successes are reported as errors, to help
keep the list of known defects as up to date as possible.
"""

# Copyright The Mbed TLS Contributors
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import os
import re
import shutil
import subprocess
import sys

#pylint: disable=unused-import
import scripts_path
from mbedtls_dev import build_tree

# PSA Compliance tests we expect to fail due to known defects in Mbed TLS / PSA Crypto
# (or the test suite).
# The test numbers correspond to the numbers used by the console output of the test suite.
# Test number 2xx corresponds to the files in the folder
# psa-arch-tests/api-tests/dev_apis/crypto/test_c0xx
EXPECTED_FAILURES = {
    # psa_hash_suspend() and psa_hash_resume() are not supported.
    # - Tracked in issue #3274
    262, 263
}

# We currently use a fork of ARM-software/psa-arch-tests, with a couple of downstream patches
# that allow it to build with MbedTLS 3, and fixes a couple of issues in the compliance test suite.
# These fixes allow the tests numbered 216, 248 and 249 to complete successfully.
#
# Once all the fixes are upstreamed, this fork should be replaced with an upstream commit/tag.
# - Tracked in issue #5145
#
# Web URL: https://github.com/bensze01/psa-arch-tests/tree/fixes-for-mbedtls-3
PSA_ARCH_TESTS_REPO = 'https://github.com/bensze01/psa-arch-tests.git'
PSA_ARCH_TESTS_REF = 'fix-pr-5736'

#pylint: disable=too-many-branches,too-many-statements,too-many-locals
def main(library_build_dir: str):
    root_dir = os.getcwd()

    in_psa_crypto_repo = build_tree.looks_like_psa_crypto_root(root_dir)

    if in_psa_crypto_repo:
        crypto_lib_filename = \
            library_build_dir + '/core/libpsacrypto.a'
    else:
        crypto_lib_filename = library_build_dir + '/library/libmbedcrypto.a'

    if not os.path.exists(crypto_lib_filename):
        subprocess.check_call([
            'cmake', '.',
                     '-GUnix Makefiles',
                     '-B', library_build_dir
        ])
        subprocess.check_call(['cmake', '--build', library_build_dir])

    psa_arch_tests_dir = 'psa-arch-tests'
    os.makedirs(psa_arch_tests_dir, exist_ok=True)
    try:
        os.chdir(psa_arch_tests_dir)

        # Reuse existing local clone
        subprocess.check_call(['git', 'init'])
        subprocess.check_call(['git', 'fetch', PSA_ARCH_TESTS_REPO, PSA_ARCH_TESTS_REF])
        subprocess.check_call(['git', 'checkout', 'FETCH_HEAD'])

        build_dir = 'api-tests/build'
        try:
            shutil.rmtree(build_dir)
        except FileNotFoundError:
            pass
        os.mkdir(build_dir)
        os.chdir(build_dir)

        extra_includes = (';{}/drivers/builtin/include'.format(root_dir)
                          if in_psa_crypto_repo else '')

        #pylint: disable=bad-continuation
        subprocess.check_call([
            'cmake', '..',
                     '-GUnix Makefiles',
                     '-DTARGET=tgt_dev_apis_stdc',
                     '-DTOOLCHAIN=HOST_GCC',
                     '-DSUITE=CRYPTO',
                     '-DPSA_CRYPTO_LIB_FILENAME={}/{}'.format(root_dir,
                                                              crypto_lib_filename),
                     ('-DPSA_INCLUDE_PATHS={}/include' + extra_includes).format(root_dir)
        ])
        subprocess.check_call(['cmake', '--build', '.'])

        proc = subprocess.Popen(['./psa-arch-tests-crypto'],
                                bufsize=1, stdout=subprocess.PIPE, universal_newlines=True)

        test_re = re.compile(
            '^TEST: (?P<test_num>[0-9]*)|'
            '^TEST RESULT: (?P<test_result>FAILED|PASSED)'
        )
        test = -1
        unexpected_successes = set(EXPECTED_FAILURES)
        expected_failures = []
        unexpected_failures = []
        for line in proc.stdout:
            print(line, end='')
            match = test_re.match(line)
            if match is not None:
                groupdict = match.groupdict()
                test_num = groupdict['test_num']
                if test_num is not None:
                    test = int(test_num)
                elif groupdict['test_result'] == 'FAILED':
                    try:
                        unexpected_successes.remove(test)
                        expected_failures.append(test)
                        print('Expected failure, ignoring')
                    except KeyError:
                        unexpected_failures.append(test)
                        print('ERROR: Unexpected failure')
                elif test in unexpected_successes:
                    print('ERROR: Unexpected success')
        proc.wait()

        print()
        print('***** test_psa_compliance.py report ******')
        print()
        print('Expected failures:', ', '.join(str(i) for i in expected_failures))
        print('Unexpected failures:', ', '.join(str(i) for i in unexpected_failures))
        print('Unexpected successes:', ', '.join(str(i) for i in sorted(unexpected_successes)))
        print()
        if unexpected_successes or unexpected_failures:
            if unexpected_successes:
                print('Unexpected successes encountered.')
                print('Please remove the corresponding tests from '
                      'EXPECTED_FAILURES in tests/scripts/compliance_test.py')
                print()
            print('FAILED')
            return 1
        else:
            print('SUCCESS')
            return 0
    finally:
        os.chdir(root_dir)

if __name__ == '__main__':
    # Default build directory
    library_build_dir = 'out_of_source_build'

    parser = argparse.ArgumentParser()
    parser.add_argument('--build-dir', nargs=1,
                        help='path to Mbed TLS / PSA Crypto build directory')
    args = parser.parse_args()

    if args.build_dir is not None:
        library_build_dir = args.build_dir[0]

    sys.exit(main(library_build_dir))
