#
# Copyright (c) 2019-2021, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import glob
import json
import logging
import os
import sys
import time
import traceback
from functools import lru_cache

import flask
import joblib
import numpy
import xgboost
from flask import Flask, Response

try:
    """check for GPU via library imports"""
    import cupy
    from cuml import ForestInference

    GPU_INFERENCE_FLAG = True

except ImportError as gpu_import_error:
    GPU_INFERENCE_FLAG = False
    print(f"\n!GPU import error: {gpu_import_error}\n")

# set to true to print incoming request headers and data
DEBUG_FLAG = False


def serve(xgboost_threshold=0.5):
    """Flask Inference Server for SageMaker hosting of RAPIDS Models"""
    app = Flask(__name__)
    logging.basicConfig(level=logging.DEBUG)

    if GPU_INFERENCE_FLAG:
        app.logger.info("GPU Model Serving Workflow")
        app.logger.info(f"> {cupy.cuda.runtime.getDeviceCount()}" f" GPUs detected \n")
    else:
        app.logger.info("CPU Model Serving Workflow")
        app.logger.info(f"> {os.cpu_count()} CPUs detected \n")

    @app.route("/ping", methods=["GET"])
    def ping():
        """SageMaker required method, ping heartbeat"""
        return Response(response="\n", status=200)

    @lru_cache
    def load_trained_model():
        """
        Cached loading of trained [ XGBoost or RandomForest ] model into memory
        Note: Models selected via filename parsing, edit if necessary
        """
        xgb_models = glob.glob("/opt/ml/model/*_xgb")
        rf_models = glob.glob("/opt/ml/model/*_rf")
        kmeans_models = glob.glob("/opt/ml/model/*_kmeans")
        app.logger.info(f"detected xgboost models : {xgb_models}")
        app.logger.info(f"detected randomforest models : {rf_models}")
        app.logger.info(f"detected kmeans models : {kmeans_models}\n\n")
        model_type = None

        start_time = time.perf_counter()

        if len(xgb_models):
            model_type = "XGBoost"
            model_filename = xgb_models[0]
            if GPU_INFERENCE_FLAG:
                # FIL
                reloaded_model = ForestInference.load(model_filename)
            else:
                # native XGBoost
                reloaded_model = xgboost.Booster()
                reloaded_model.load_model(fname=model_filename)

        elif len(rf_models):
            model_type = "RandomForest"
            model_filename = rf_models[0]
            reloaded_model = joblib.load(model_filename)

        elif len(kmeans_models):
            model_type = "KMeans"
            model_filename = kmeans_models[0]
            reloaded_model = joblib.load(model_filename)
        else:
            raise Exception("! No trained models detected")

        exec_time = time.perf_counter() - start_time
        app.logger.info(f"> model {model_filename} " f"loaded in {exec_time:.5f} s \n")

        return reloaded_model, model_type, model_filename

    @app.route("/invocations", methods=["POST"])
    def predict():
        """
        Run CPU or GPU inference on input data,
        called every time an incoming request arrives
        """
        # parse user input
        try:
            if DEBUG_FLAG:
                app.logger.debug(flask.request.headers)
                app.logger.debug(flask.request.content_type)
                app.logger.debug(flask.request.get_data())

            string_data = json.loads(flask.request.get_data())
            query_data = numpy.array(string_data)

        except Exception:
            return Response(
                response="Unable to parse input data"
                "[ should be json/string encoded list of arrays ]",
                status=415,
                mimetype="text/csv",
            )

        # cached [reloading] of trained model to process incoming requests
        reloaded_model, model_type, model_filename = load_trained_model()

        try:
            start_time = time.perf_counter()
            if model_type == "XGBoost":
                app.logger.info(
                    "running inference using XGBoost model :" f"{model_filename}"
                )

                if GPU_INFERENCE_FLAG:
                    predictions = reloaded_model.predict(query_data)
                else:
                    dm_deserialized_data = xgboost.DMatrix(query_data)
                    predictions = reloaded_model.predict(dm_deserialized_data)

                predictions = (predictions > xgboost_threshold) * 1.0

            elif model_type == "RandomForest":
                app.logger.info(
                    "running inference using RandomForest model :" f"{model_filename}"
                )

                if "gpu" in model_filename and not GPU_INFERENCE_FLAG:
                    raise Exception(
                        "attempting to run CPU inference "
                        "on a GPU trained RandomForest model"
                    )

                predictions = reloaded_model.predict(query_data.astype("float32"))

            elif model_type == "KMeans":
                app.logger.info(
                    "running inference using KMeans model :" f"{model_filename}"
                )

                if "gpu" in model_filename and not GPU_INFERENCE_FLAG:
                    raise Exception(
                        "attempting to run CPU inference "
                        "on a GPU trained KMeans model"
                    )

                predictions = reloaded_model.predict(query_data.astype("float32"))

            app.logger.info(f"\n predictions: {predictions} \n")
            exec_time = time.perf_counter() - start_time
            app.logger.info(f" > inference finished in {exec_time:.5f} s \n")

            # return predictions
            return Response(
                response=json.dumps(predictions.tolist()),
                status=200,
                mimetype="text/csv",
            )

        # error during inference
        except Exception as inference_error:
            app.logger.error(inference_error)
            return Response(
                response=f"Inference failure: {inference_error}\n",
                status=400,
                mimetype="text/csv",
            )

    # initial [non-cached] reload of trained model
    reloaded_model, model_type, model_filename = load_trained_model()

    # trigger start of Flask app
    app.run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    try:
        serve()
        sys.exit(0)  # success exit code

    except Exception:
        traceback.print_exc()
        sys.exit(-1)  # failure exit code

"""
airline model inference test [ 3 non-late flights, and a one late flight ]
curl -X POST --header "Content-Type: application/json" --data '[[ ... ]]' http://0.0.0.0:8080/invocations
"""
