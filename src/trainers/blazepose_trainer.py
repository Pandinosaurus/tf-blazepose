import os
import pathlib
import importlib

import tensorflow as tf
from tensorflow.keras.callbacks import ModelCheckpoint, TensorBoard

from ..model_type import ModelType
from ..train_phase import TrainPhase
from ..models.blazepose import BlazePose

from .losses import euclidean_distance_loss, focal_tversky, focal_loss

def train(config):
    """Train model

    Args:
        config (dict): Training configuration from configuration file
    """

    train_config = config["train"]
    model_config = config["model"]

    # Dataloader
    datalib = importlib.import_module("src.data.{}".format(config["data_loader"]))
    DataSequence = datalib.DataSequence

    # Initialize model
    model_type = ModelType(model_config["model_type"])
    model = BlazePose(
        model_config["num_joints"], model_type).build_model()

    # Freeze regression branch when training heatmap
    train_phase = TrainPhase(train_config.get("train_phase", "UNKNOWN"))
    if train_phase == train_phase.HEATMAP:
        print("Freeze these layers:")
        for layer in model.layers:
            if layer.name.startswith("regression"):
                print(layer.name)
                layer.trainable = False
    # Freeze heatmap branch when training regression
    elif train_phase == train_phase.REGRESSION:
        print("Freeze these layers:")
        for layer in model.layers:
            if not layer.name.startswith("regression"):
                print(layer.name)
                layer.trainable = False

    print(model.summary())

    loss_functions = {
        "heatmap": train_config["heatmap_loss"],
        "joints": train_config["keypoint_loss"]
    }
    
    # Replace all names with functions for custom losses
    for k in loss_functions.keys():
        if loss_functions[k] == "euclidean_distance_loss":
            loss_functions[k] = euclidean_distance_loss
        elif loss_functions[k] == "focal_tversky":
            loss_functions[k] = focal_tversky
        elif loss_functions[k] == "huber":
            loss_functions[k] = tf.keras.losses.Huber()
        elif loss_functions[k] == "focal":
            loss_functions[k] = focal_loss(gamma=2, alpha=0.25)

    loss_weights = train_config["loss_weights"]
    model.compile(optimizer=tf.optimizers.Adam(train_config["learning_rate"]),
                  loss=loss_functions, loss_weights=loss_weights)


    # Load pretrained model
    if train_config["load_weights"]:
        print("Loading model weights: " +
              train_config["pretrained_weights_path"])
        model.load_weights(train_config["pretrained_weights_path"])

    # Create experiment folder
    exp_path = os.path.join("experiments/{}".format(config["experiment_name"]))
    pathlib.Path(exp_path).mkdir(parents=True, exist_ok=True)

    # Define the callbacks
    tb_log_path = os.path.join(exp_path, "tb_logs")
    tb = TensorBoard(log_dir=tb_log_path, write_graph=True)
    model_folder_path = os.path.join(exp_path, "models")
    pathlib.Path(model_folder_path).mkdir(parents=True, exist_ok=True)
    mc = ModelCheckpoint(filepath=os.path.join(
        model_folder_path, "model_ep{epoch:03d}.h5"), save_weights_only=True, save_format="h5", verbose=1)

    # Load data
    train_dataset = DataSequence(
        config["data"]["train_images"],
        config["data"]["train_labels"],
        batch_size=train_config["train_batch_size"],
        input_size=(model_config["im_width"], model_config["im_height"]),
        heatmap_size=(model_config["heatmap_width"], model_config["heatmap_height"]),
        heatmap_sigma=model_config["heatmap_kp_sigma"],
        n_points=model_config["num_joints"],
        symmetry_point_ids=config["data"]["symmetry_point_ids"],
        shuffle=True, augment=True, random_flip=True, random_rotate=True, random_scale_on_crop=True)
    val_dataset = DataSequence(
        config["data"]["val_images"],
        config["data"]["val_labels"],
        batch_size=train_config["val_batch_size"],
        input_size=(model_config["im_width"], model_config["im_height"]),
        heatmap_size=(model_config["heatmap_width"], model_config["heatmap_height"]),
        heatmap_sigma=model_config["heatmap_kp_sigma"],
        n_points=model_config["num_joints"],
        symmetry_point_ids=config["data"]["symmetry_point_ids"],
        shuffle=False, augment=False, random_flip=False, random_rotate=False, random_scale_on_crop=False)

    # Initial epoch. Use when continue training
    initial_epoch = train_config.get("initial_epoch", 0)

    # Train
    model.fit(train_dataset,
              epochs=train_config["nb_epochs"],
              steps_per_epoch=len(train_dataset),
              validation_data=val_dataset,
              validation_steps=len(val_dataset),
              callbacks=[tb, mc],
              initial_epoch=initial_epoch,
              verbose=1)


def load_model(config, model_path):
    """Load pretrained model

    Args:
        config (dict): Model configuration
        model (str): Path to h5 model to be tested
    """

    model_config = config["model"]

    # Initialize model and load weights
    model = BlazePose(model_config["num_joints"], ModelType(model_config["model_type"])).build_model()
    model.compile()
    model.load_weights(model_path)

    return model