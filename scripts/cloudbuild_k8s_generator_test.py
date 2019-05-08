# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
import tempfile
import cloudbuild_k8s_generator

CLOUDBUILD_OUTPUT = """
# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

##################################################################################
## This file is generated by cloudbuild_k8s_generator.py. Do not manually edit. ##
##################################################################################

timeout: 1800s # 30m
options:
  machineType: 'N1_HIGHCPU_8'
substitutions:
  _CLUSTER_NAME: cluster-1
  _CLUSTER_LOCATION: us-central1
steps:

- id: Pull Dev Image
  name: gcr.io/cloud-builders/docker
  dir: k8s
  entrypoint: bash
  args:
  - -exc
  - |
    TAG="$$(cat ./MARKETPLACE_TOOLS_TAG)"
    docker pull "gcr.io/cloud-marketplace-tools/k8s/dev:$$TAG"
    docker tag "gcr.io/cloud-marketplace-tools/k8s/dev:$$TAG" "gcr.io/cloud-marketplace-tools/k8s/dev:local"

- id: Get Kubernetes Credentials
  name: gcr.io/cloud-builders/gcloud
  waitFor:
  - '-'
  args:
  - container
  - clusters
  - get-credentials
  - '$_CLUSTER_NAME'
  - --region
  - '$_CLUSTER_LOCATION'
  - --project
  - '$PROJECT_ID'

- id: Copy kubectl Credentials
  name: gcr.io/google-appengine/debian9
  waitFor:
  - Get Kubernetes Credentials
  entrypoint: bash
  args:
  - -exc
  - |
    mkdir -p /workspace/.kube/
    cp -r $$HOME/.kube/ /workspace/

- id: Copy gcloud Credentials
  name: gcr.io/google-appengine/debian9
  waitFor:
  - Get Kubernetes Credentials
  entrypoint: bash
  args:
  - -exc
  - |
    mkdir -p /workspace/.config/gcloud/
    cp -r $$HOME/.config/gcloud/ /workspace/.config/

- id: Build wordpress
  name: gcr.io/cloud-marketplace-tools/k8s/dev:local
  env:
  - 'KUBE_CONFIG=/workspace/.kube'
  - 'GCLOUD_CONFIG=/workspace/.config/gcloud'
  # Use local Docker network named cloudbuild as described here:
  # https://cloud.google.com/cloud-build/docs/overview#build_configuration_and_build_steps
  - 'EXTRA_DOCKER_PARAMS=--net cloudbuild'
  dir: k8s/wordpress
  args:
  - make
  - -j4
  - app/build

- id: Verify wordpress
  name: gcr.io/cloud-marketplace-tools/k8s/dev:local
  waitFor:
  - Copy kubectl Credentials
  - Copy gcloud Credentials
  - Pull Dev Image
  - Build wordpress
  env:
  - 'KUBE_CONFIG=/workspace/.kube'
  - 'GCLOUD_CONFIG=/workspace/.config/gcloud'
  # Use local Docker network named cloudbuild as described here:
  # https://cloud.google.com/cloud-build/docs/overview#build_configuration_and_build_steps
  - 'EXTRA_DOCKER_PARAMS=--net cloudbuild'
  dir: k8s/wordpress
  args:
  - make
  - -j4
  - app/verify
""".strip()

CLOUDBUILD_OUTPUT_WITH_EXTRA_CONFIG = ''.join([CLOUDBUILD_OUTPUT, '\n', """
- id: Verify wordpress (Public service and ingress)
  name: gcr.io/cloud-marketplace-tools/k8s/dev:local
  waitFor:
  - Copy kubectl Credentials
  - Copy gcloud Credentials
  - Pull Dev Image
  - Build wordpress
  env:
  - 'KUBE_CONFIG=/workspace/.kube'
  - 'GCLOUD_CONFIG=/workspace/.config/gcloud'
  # Use local Docker network named cloudbuild as described here:
  # https://cloud.google.com/cloud-build/docs/overview#build_configuration_and_build_steps
  - 'EXTRA_DOCKER_PARAMS=--net cloudbuild'
  # Non-default variables.
  - 'PUBLIC_SERVICE_AND_INGRESS_ENABLED=true'
  - 'METRICS_EXPORTER_ENABLED=true'
  dir: k8s/wordpress
  args:
  - make
  - -j4
  - app/verify
"""
]).strip()


class CloudBuildK8sGeneratorTest(unittest.TestCase):

  def test_path(self):
    cloudbuild = cloudbuild_k8s_generator.CloudBuildConfig(solution='wordpress')
    cloudbuild.path = '/tmp/wordpress.yaml'
    self.assertEqual(cloudbuild.path, '/tmp/wordpress.yaml')

  def test_exists(self):
    with tempfile.NamedTemporaryFile(delete=True) as f:
      cloudbuild = cloudbuild_k8s_generator.CloudBuildConfig(solution='unknown')
      cloudbuild.path = f.name
      self.assertTrue(cloudbuild.exists())

  def test_verify(self):
    cloudbuild_config = """
    steps:
    - id: Build unknown
      name: gcr.io/cloud-builders/docker
      dir: k8s
    """
    cloudbuild_template = """
    steps:
    - id: Build {{ solution }}
      name: gcr.io/cloud-builders/docker
      dir: k8s
    """
    with tempfile.NamedTemporaryFile(delete=True) as f:
      f.write(cloudbuild_config)
      f.flush()

      cloudbuild = cloudbuild_k8s_generator.CloudBuildConfig(solution='unknown')
      cloudbuild.path = f.name
      self.assertFalse(cloudbuild.verify())

      cloudbuild.template = cloudbuild_template
      self.assertTrue(cloudbuild.verify())

  def test_template(self):
    extra_configs = [{
        'name': 'Public service and ingress',
        'env_vars': ['PUBLIC_SERVICE_AND_INGRESS_ENABLED=true']
    }]
    cloudbuild_template = """
    steps:
    - id: Build {{ solution }}
      name: gcr.io/cloud-builders/docker
      dir: k8s

    {%- for extra_config in extra_configs %}

    - id: Verify {{ solution }} ({{ extra_config['name'] }})
      name: gcr.io/cloud-builders/docker
      dir: k8s
      env:
      {%- for env_var in extra_config['env_vars'] %}
      - '{{ env_var }}'
      {%- endfor %}

    {%- endfor %}
    """.strip()

    cloudbuild = cloudbuild_k8s_generator.CloudBuildConfig(solution='wordpress')
    self.assertIsNotNone(cloudbuild.generate())

    cloudbuild = cloudbuild_k8s_generator.CloudBuildConfig(solution='wordpress')
    cloudbuild.extra_configs = []
    self.assertIsNotNone(cloudbuild.generate())

    cloudbuild = cloudbuild_k8s_generator.CloudBuildConfig(solution='wordpress')
    cloudbuild.template = cloudbuild_template
    self.assertEqual(
        cloudbuild.generate(), """
    steps:
    - id: Build wordpress
      name: gcr.io/cloud-builders/docker
      dir: k8s
    """.strip())

    cloudbuild = cloudbuild_k8s_generator.CloudBuildConfig(solution='wordpress')
    cloudbuild.extra_configs = extra_configs
    cloudbuild.template = cloudbuild_template
    self.assertEqual(
        cloudbuild.generate(), """
    steps:
    - id: Build wordpress
      name: gcr.io/cloud-builders/docker
      dir: k8s

    - id: Verify wordpress (Public service and ingress)
      name: gcr.io/cloud-builders/docker
      dir: k8s
      env:
      - 'PUBLIC_SERVICE_AND_INGRESS_ENABLED=true'
    """.strip())

  def test_generate(self):
    extra_configs = [{
        'name':
            'Public service and ingress',
        'env_vars': [
            'PUBLIC_SERVICE_AND_INGRESS_ENABLED=true',
            'METRICS_EXPORTER_ENABLED=true'
        ]
    }]

    cloudbuild = cloudbuild_k8s_generator.CloudBuildConfig(solution='wordpress')
    self.assertEqual(cloudbuild.generate(), CLOUDBUILD_OUTPUT)

    cloudbuild.extra_configs = extra_configs
    self.assertEqual(cloudbuild.generate(), CLOUDBUILD_OUTPUT_WITH_EXTRA_CONFIG)

  def test_save(self):
    cloudbuild_config = """
    steps:
    - id: Build unknown
      name: gcr.io/cloud-builders/docker
      dir: k8s
    """
    with tempfile.NamedTemporaryFile(delete=True) as f:
      cloudbuild = cloudbuild_k8s_generator.CloudBuildConfig(
          solution='wordpress')
      cloudbuild.template = cloudbuild_config
      cloudbuild.path = f.name
      cloudbuild.save()
      self.assertEqual(f.read(), cloudbuild_config)

  def test_remove(self):
    with tempfile.NamedTemporaryFile(delete=False) as f:
      cloudbuild = cloudbuild_k8s_generator.CloudBuildConfig(
          solution='wordpress')
      cloudbuild.path = f.name
      cloudbuild.remove()
      self.assertFalse(cloudbuild.exists())


if __name__ == '__main__':
  unittest.main()
