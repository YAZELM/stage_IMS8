"""Affiche les topics disponibles dans un fichier ROS bag.

Ce petit outil sert surtout avant extraction: il permet de verifier les noms de
topics et le nombre de messages sans modifier le bag.
"""
import argparse

from utils import open_bag


def inspect_bag(bag_path):
    # On liste les connexions du bag avec leur type ROS et leur nombre de messages.
    # C'est la verification la plus directe avant de choisir un topic RGB ou DVS.
    with open_bag(bag_path) as bag:
        print("\nTopics in:", bag_path)
        print("-" * 80)
        for connection in bag.connections:
            print(connection.topic)
            print("  type:    ", connection.msgtype)
            print("  messages:", connection.msgcount)
            print()


def main():
    parser = argparse.ArgumentParser(description="Inspect topics inside a ROS1 .bag file")
    parser.add_argument("bag")
    args = parser.parse_args()
    inspect_bag(args.bag)


if __name__ == "__main__":
    main()
