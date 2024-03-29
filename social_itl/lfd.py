import sentence_transformers
from social_itl.furhat import UserSpeech, SpeakerRole
from social_itl.utils import get_logger, get_data_path
from typing import AsyncGenerator
import pickle
import asyncio
import numpy as np
from tqdm import tqdm
from functools import partialmethod
tqdm.__init__ = partialmethod(tqdm.__init__, disable=True)
from simcse import SimCSE
from scipy.spatial.distance import cosine
similarity_model = SimCSE("princeton-nlp/sup-simcse-bert-base-uncased")


class LfD():
    def __init__(self, participant_id: str = '0'):
        self.pairs = []
        self.logger = get_logger(f'LfD_{participant_id}', 'lfd', unique=True)
        self.participant_id = participant_id
        if participant_id != '-1' and (get_data_path('lfd') / f'p_{self.participant_id}.pkl').exists():
            self.load(vectorize=False)
        self.actions = None
        self.states = None

    def save(self):
        path = get_data_path('lfd') / f'p_{self.participant_id}.pkl'
        with open(path, 'wb') as f:
            print("Saving pairs", self.pairs, "Particpant", self.participant_id)
            pickle.dump(self.pairs, f)

    def load(self, vectorize=True):
        path = get_data_path('lfd') / f'p_{self.participant_id}.pkl'
        with open(path, 'rb') as f:
            self.pairs = pickle.load(f)
            print(self.pairs)
        if vectorize:
            self.vectorize()

    async def train(self, data: AsyncGenerator[UserSpeech, None]):
        state = None
        action = None
        try:
            async for speech in data:
                if speech.role == SpeakerRole.CUSTOMER:
                    self.logger.info(f'Customer: {speech.text}')
                    if action is not None:
                        if state is None:
                            state = ''
                        self.pairs.append((state, action))
                        action = None
                        state = speech.text
                    elif state is None:
                        state = speech.text
                    else:
                        state = state + ' ' + speech.text
                elif speech.role == SpeakerRole.EMPLOYEE:
                    self.logger.info(f'Employee: {speech.text}')
                    if action is None:
                        action = speech.text
                    else:
                        action = action + ' ' + speech.text
        except asyncio.CancelledError:
            print("Cancelled")
            if action is not None:
                if state is None:
                    state = ''
                self.pairs.append((state, action))
        print(self.pairs)

    def vectorize(self):
        states, actions = zip(*self.pairs)
        print(states)
        states = similarity_model.encode(list(states), return_numpy=True)
        actions = np.concatenate([np.zeros((1, 768)), similarity_model.encode(list(actions), return_numpy=True)[:-1]])
        self.actions = actions
        self.states = states

    def get_action(self, state: str, prev_action: str):
        if prev_action == '':
            action_embedding = np.zeros((1, 768))
        else:
            action_embedding = similarity_model.encode([prev_action], return_numpy=True)
        state_embedding = similarity_model.encode([state], return_numpy=True)
        dist = 0.8 * np.linalg.norm(self.states - state_embedding, axis=1) + 0.2 * np.linalg.norm(self.actions - action_embedding, axis=1)
        match_idx = np.argmin(dist)
        return self.pairs[match_idx][1], dist[match_idx]
        