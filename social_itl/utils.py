from importlib_resources import files, as_file
import logging
import datetime
from pathlib import Path

def get_logger(name: str, folder: str = None, unique: bool = False):
    if unique:
        name = name + '-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S') + '.txt'
    path = files('multimodal') / 'logs'
    if folder is not None:
        path = path / folder
    path = path / name
    logger = logging.getLogger(str(path))
    logger.setLevel(logging.DEBUG)
    with as_file(path) as p:
        p.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(p, mode='w+')
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

def get_data_path(name: str):
    data_path = files('multimodal') / 'data' / name
    with as_file(data_path) as p:
        if p.is_dir():
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
        return p

def get_model_path(name: str):
    model_path = files('multimodal') / 'models' / name
    with as_file(model_path) as p:
        return p