# -*- coding: utf-8 -*-

# Copyright 2018 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
import os
import re
import random
import requests
import sys

import pandas as pd

from flask import Flask
from flask import jsonify
from flask import render_template
from flask import g, request
from flask import url_for
import logging
from googleapiclient import discovery
from oauth2client.client import GoogleCredentials

# similar to T2T's query.py
# https://github.com/tensorflow/tensor2tensor/blob/master/tensor2tensor/serving/query.py
from tensor2tensor import problems as problems_lib  # pylint: disable=unused-import
from tensor2tensor.data_generators import text_encoder
from tensor2tensor.utils import registry
from tensor2tensor.utils import usr_dir
import tensorflow as tf
from tensor2tensor.serving import serving_utils

credentials = GoogleCredentials.get_application_default()
api = discovery.build('ml', 'v1', credentials=credentials)

app = Flask(__name__)

model_name = os.getenv('MODEL_NAME', 'ghsumm')
problem_name = os.getenv('PROBLEM_NAME', 'gh_problem')
t2t_usr_dir = os.getenv('T2T_USR_DIR', 'ghsumm/trainer')
hparams_name = os.getenv('HPARAMS', 'transformer_prepend')
data_dir = os.getenv('DATADIR', 'gs://aju-dev-demos-codelabs/kubecon/t2t_data_gh_all/')
github_token = os.getenv('GH_TOKEN', 'xxx')

server = os.getenv('TFSERVING_HOST', 'ghsumm.kubeflow')
print("using server: %s" % server)
servable_name = os.getenv('TF_SERVABLE_NAME', 'ghsumm')
print("using model servable name: %s" % servable_name)

# SAMPLE_DATA_URL = ('https://storage.googleapis.com/kubeflow-examples/'
#                    'github-issue-summarization-data/github_issues_sample.csv')
SAMPLE_ISSUES = './github_issues_sample.csv'

# SERVER_URL = 'http://130.211.206.140:8500/v1/models/ghsumm:predict'
SERVER_URL = 'http://' + server + ':8500/v1/models/' + servable_name + ':predict'

def get_issue_body(issue_url):
  issue_url = re.sub('.*github.com/', 'https://api.github.com/repos/',
                     issue_url)
  tf.logging.info("issue url: %s", issue_url)
  tf.logging.info("using GH token: %s" , github_token)
  response = requests.get(
    issue_url, headers={
      'Authorization': 'token {}'.format(github_token)
    }).json()
  tf.logging.info("----response from url fetch: %s", response)
  return response['body']


@app.route('/')
def index():
  return render_template('index.html')

# @app.route('/form')
# def input_form():
#   return render_template('index.html')

@app.route("/random_github_issue", methods=['GET'])
def random_github_issue():
  github_issues = getattr(g, '_github_issues', None)
  if github_issues is None:
    github_issues = g._github_issues = pd.read_csv(
      SAMPLE_ISSUES).body.tolist()
  random_issue = github_issues[random.randint(0,
                                 len(github_issues) - 1)]
  tf.logging.info("----random issue text: %s", random_issue)
  return jsonify({'body': random_issue})


@app.route("/summary", methods=['POST'])
def summary():
  """Main prediction route.

  Provides a machine-generated summary of the given text. Sends a request to a live
  model trained on GitHub issues.
  """
  global problem
  if problem is None:
    init()
  request_fn = make_tfserving_rest_request_fn(
      servable_name=servable_name,
      server=server)

  if request.method == 'POST':
    issue_text = request.form["issue_text"]
    issue_url = request.form["issue_url"]
    if issue_url:
      print("fetching issue from URL...")
      issue_text = get_issue_body(issue_url)
    tf.logging.info("issue_text: %s", issue_text)
    outputs = serving_utils.predict([issue_text], problem, request_fn)
    outputs, = outputs
    output, score = outputs
    tf.logging.info("output: %s", output)

    return jsonify({'summary': output, 'body': issue_text})

  return ('', 204)

problem = None
def init():
  # global input_encoder, output_decoder, fname, problem
  global problem
  tf.logging.set_verbosity(tf.logging.INFO)
  tf.logging.info("importing ghsumm/trainer from {}".format(t2t_usr_dir))
  usr_dir.import_usr_dir(t2t_usr_dir)
  print(t2t_usr_dir)
  problem = registry.problem(problem_name)
  hparams = tf.contrib.training.HParams(data_dir=os.path.expanduser(data_dir))
  problem.get_hparams(hparams)

def make_tfserving_rest_request_fn(servable_name, server):
  """Wraps function to make CloudML Engine requests with runtime args."""

  def _make_tfserving_rest_request_fn(examples):
    """..."""
    # api = discovery.build("ml", "v1", credentials=credentials)
    # parent = "projects/%s/models/%s/versions/%s" % (cloud.default_project(),
                                                    # model_name, version)
    input_data = {
        "instances": [{
            "input": {
                "b64": base64.b64encode(ex.SerializeToString())
            }
        } for ex in examples]
    }

    input_data_str = json.dumps(input_data)
    response = requests.post(SERVER_URL, json=input_data)
    predictions = response.json()['predictions']
    tf.logging.info("Predictions: %s", predictions)
    return predictions

  return _make_tfserving_rest_request_fn

@app.errorhandler(500)
def server_error(e):
    logging.exception('An error occurred during a request.')
    return """
    An internal error occurred: <pre>{}</pre>
    See logs for full stacktrace.
    """.format(e), 500

if __name__ == '__main__':
    app.run(port=8080, debug=True)