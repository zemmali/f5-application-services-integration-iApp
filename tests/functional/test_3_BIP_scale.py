#!/usr/bin/env python
# Copyright (c) 2017 F5 Networks, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.
#

import json
import logging
import os

import ipaddress
import pytest

from src.appservices.TestTools import get_payload_list
from src.appservices.TestTools import load_payload
from src.appservices.TestTools import strip_payload_name
from src.appservices.TestTools import update_payload_name
from src.appservices.exceptions import AppServiceDeploymentException
from src.appservices.exceptions import AppServiceDeploymentVerificationException
from src.appservices.exceptions import AppServiceRemovalException
from src.appservices.exceptions import RESTException
from src.appservices.tools import mk_dir
from src.appservices.tools import save_json


@pytest.fixture(scope='module')
def get_scale_size(request):
    return request.config.getoption("--scale_size")


def test_functional_tests_at_scale(
        get_config, bip_client, prepare_tests, get_scale_size, setup_logging):
    test_results = {}

    logger = logging.getLogger(__name__)

    log_dir = os.path.join("logs", get_config['session_id'], 'run')
    mk_dir(log_dir)

    for payload_file in get_payload_list(get_config):

        payload = load_payload(get_config['payloads_dir'], payload_file)

        if payload["variables"][7]['value'] != "172.16.0.100":
            # Skipping (payloads/'tests'/Application Services) that depend on each other
            continue

        if payload['name'] in ['test_vs_standard_https_multi_listeners']:
            # Skipping (payloads/'tests'/Application Services) due to:
            # {
            #     "apiError": 3,
            #     "code": 400,
            #     "errorStack": [],
            #     "message": "01070333:3: Virtual Server /Common/test_vs_standard_https_multi_listeners_1.app/test_vs_standard_https_addlisteners_vs_idx_0_445
            # illegally shares destination address, source address, service port, ip-protocol,
            #  and vlan with Virtual Server /Common/test_vs_standard_https_multi_listeners_0.app/test_vs_standard_https_addlisteners_vs_idx_0_445."
            # }
            continue

        pool_addr = ipaddress.ip_address(u"172.16.0.100")

        test_results[payload['name']] = {
            'scale_size': get_scale_size
        }

        for deployment_no in range(get_scale_size):
            payload['name'] = update_payload_name(
                payload['name'], deployment_no)
            payload["variables"][7]['value'] = str(
                pool_addr+deployment_no)

            test_run_log_dir = os.path.abspath(
                os.path.join(log_dir, strip_payload_name(payload['name']),
                             str(deployment_no))
            )

            try:
                bip_client.deploy_app_service(payload)
                bip_client.verify_deployment_result(
                    payload, test_run_log_dir)
                test_results[strip_payload_name(payload['name'])]['completed'] = deployment_no + 1

            except (AppServiceDeploymentException, RESTException,
                    AppServiceDeploymentVerificationException) as ex:
                test_results[strip_payload_name(payload['name'])]['deployment_exception'] = str(ex)
                logger.exception(ex)
                bip_client.download_logs(test_run_log_dir)
                bip_client.download_qkview(test_run_log_dir)
                break

        for removal_no in range(deployment_no + 1):
            payload['name'] = update_payload_name(
                payload['name'], removal_no)
            try:
                bip_client.remove_app_service(payload)
            except AppServiceRemovalException as ex:
                test_results[strip_payload_name(payload['name'])]['removal_exception'] = str(ex)
                logger.exception(ex)

    print(json.dumps(test_results, indent=4, sort_keys=True))

    save_json(os.path.join(log_dir, 'scale_test_result.json'), test_results)

    for payload_name in test_results:
        assert 'deployment_exception' not in test_results[payload_name]
        assert 'removal_exception' not in test_results[payload_name]