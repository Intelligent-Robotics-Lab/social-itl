from py_trees.trees import BehaviourTree
from py_trees.composites import Sequence
from py_trees.behaviour import Behaviour
from py_trees.display import ascii_tree
from multimodal.tasklearning.behaviours import Conditional, LearnableSequence, Approach, NullBehaviour, PersonSays, CustomBehavior, LearnableBehaviour
from multimodal.tasklearning.tree_parser import TreeParser, ParseError
from multimodal.nlp.sentence_classifier import SentenceType

class Prompt:
    def __init__(self, text: str, needs_response: bool):
        self.text = text
        self.needs_response = needs_response

class Response:
    def __init__(self, text: str, sentence_type: SentenceType) -> None:
        self.text = text
        self.sentence_type = sentence_type

class TaskLearner:
    def __init__(self, root : Behaviour = None):
        if root is None:
            self.root = CustomBehavior(name="Root")
        else:
            self.root = root
        self.tree = BehaviourTree(root=self.root)
        self.root.add_child(Approach())
        self.parser = TreeParser()

    def find_unlearned_behaviour(self, parent : Behaviour = None):
        if parent is None:
            parent = self.root
        # print(parent.name)
        for child in parent.children:
            if isinstance(child, LearnableBehaviour) and not child.learned:
                return self.find_unlearned_behaviour(child)
        # No children are unlearned, so return the parent
        return parent

    def generate_prompts(self):
        while True:
            print(ascii_tree(self.tree.root))
            if self.root.learned:
                # Done learning, stop generating prompts
                raise StopIteration()
            unlearned = self.find_unlearned_behaviour()
            if isinstance(unlearned, LearnableSequence):
                unlearned = unlearned.parent
            print(f"Unlearned: {unlearned.name}")
            try:
                if isinstance(unlearned, CustomBehavior):
                    if unlearned == self.root:
                        response: Response = yield Prompt(f'What should I do after {self.root.children[-1].description}?', True)
                        
                        if response.sentence_type == SentenceType.INSTRUCTION:
                            self.parser.append_tree(response.text, self.tree, unlearned)
                        elif response.sentence_type == SentenceType.DONE:
                            self.root.learned = True
                            raise StopIteration()
                        elif response.sentence_type == SentenceType.MISRECOGNIZED:
                            self.root.remove_child(self.root.children[-1])
                            yield Prompt("I'm sorry I misheard you, let's try again", False)
                        else:
                            raise Exception(f"Unhandled sentence type: {response.sentence_type}")
                    else:
                        if len(unlearned.children) == 0:
                            # Newly created behavior
                            response = yield Prompt(f'How do I {unlearned.name}?', True)
                            if response.sentence_type == SentenceType.INSTRUCTION:
                                self.parser.append_tree(response.text, self.tree, unlearned)
                            elif response.sentence_type == SentenceType.MISRECOGNIZED:
                                unlearned.parent.remove_child(unlearned)
                                yield Prompt("I'm sorry I misheard you, let's go back and try again", False)
                        else:
                            # Existing behavior
                            response = yield Prompt(f'What is the next step of {unlearned.gerund}?', True)
                            # print(f"Response: {response}")
                            if response.sentence_type == SentenceType.INSTRUCTION:
                                self.parser.append_tree(response.text, self.tree, unlearned)
                            elif response.sentence_type == SentenceType.DONE:
                                unlearned.learned = True
                                yield Prompt(f"Okay, I've learned how to {unlearned.name}", False)

                elif isinstance(unlearned, Conditional):
                    response = yield Prompt(f'Should I do anything else when {unlearned.if_statement.children[0].description}?', True)
                    if response.sentence_type == SentenceType.INSTRUCTION:
                        self.parser.append_tree(response.text, self.tree, unlearned)
                    elif response == SentenceType.DONE:
                        unlearned.if_statement.learned = True
                        yield Prompt(f"Okay, I've learned what to do when {unlearned.if_statement.children[0].description}", False)
                        text = unlearned.if_statement.children[0].text
                        if text == "yes":
                            response = yield Prompt(f'What should I do if the person says no?', True)
                        elif text == "no":
                            response = yield Prompt(f'What should I do if the person says yes?', True)
                        else:
                            unlearned.add_else(NullBehaviour())
                            unlearned.learned = True
                            continue
                        action = self.parser.append_tree(response.text)
                        unlearned.add_else(action)
                        unlearned.learned = True
                else:
                    raise Exception(f"Unknown behaviour type: {type(unlearned)}")
            except ParseError as e:
                yield Prompt("I'm sorry, I don't quite understand what you said, let's try again", False)
                            

