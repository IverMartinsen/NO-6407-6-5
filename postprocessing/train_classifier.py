import os
import sys

sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "vit"))

import torch
import argparse
import vit.vit_utils as vit_utils
import torchvision
import numpy as np
import pandas as pd
import vit.vision_transformer as vits
from time import time
from PIL import Image
from torchvision import transforms
from sklearn.metrics import classification_report
from sklearn.utils.class_weight import compute_class_weight
from sklearn.model_selection import train_test_split, StratifiedKFold


parser = argparse.ArgumentParser()
parser.add_argument("--batch_size", type=int, default=32)
parser.add_argument("--lr", type=float, default=1e-4)
parser.add_argument("--device", type=str, default="cuda")
parser.add_argument("--pretrained_weights", type=str, default="")
parser.add_argument("--epochs", type=int, default=100)
parser.add_argument("--data_dir", type=str, default="data/labelled imagefolders/imagefolder_20")
parser.add_argument("--num_workers", type=int, default=4)
parser.add_argument("--weight_decay", type=float, default=0.0)
parser.add_argument("--fold", type=int, default=0)
parser.add_argument("--backbone_arch", type=str, default="vit_small")
parser.add_argument("--output_dir", type=str, default="")
args = parser.parse_args()


# load the data
print("Loading data...")
transform = transforms.Compose([
    transforms.ColorJitter(brightness=0.0, contrast=0.0, saturation=0.0, hue=0.1),
    transforms.RandomResizedCrop(224, scale=(0.5, 1.0), interpolation=Image.BICUBIC),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomVerticalFlip(p=0.5),
    vit_utils.GaussianBlur(p=0.5),
    transforms.ToTensor(),
    transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
])

dataset = torchvision.datasets.ImageFolder(args.data_dir, transform=transform)

skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
split_gen = skf.split(np.arange(len(dataset)), dataset.targets)

for i, (i_tr, i_val) in enumerate(split_gen): # get the i-th fold
    if i == args.fold:
        break

x_tr, x_val = torch.utils.data.Subset(dataset, i_tr), torch.utils.data.Subset(dataset, i_val)

tr_loader = torch.utils.data.DataLoader(
    x_tr,
    batch_size=args.batch_size,
    shuffle=True,
    num_workers=args.num_workers,
    pin_memory=True,
)

val_loader = torch.utils.data.DataLoader(
    x_val,
    batch_size=args.batch_size,
    shuffle=False,
    num_workers=args.num_workers,
    pin_memory=True,
)

print(f"Number of training images: {len(i_tr)}")
print(f"Number of validation images: {len(i_val)}")

# load the model
pretrained_model = vits.__dict__[args.backbone_arch](patch_size=16, num_classes=0, img_size=[224])
vit_utils.load_pretrained_weights(pretrained_model, args.pretrained_weights, "teacher", args.backbone_arch, 16)


class LinearClassifier(torch.nn.Module):
    def __init__(self, input_dim, output_dim):
        super(LinearClassifier, self).__init__()
        self.linear = torch.nn.Linear(input_dim, output_dim)
    
    def forward(self, x):
        return self.linear(x)


input_dim = {"vit_small": 384, "vit_base": 768}[args.backbone_arch]

classifier = LinearClassifier(input_dim, 20)

model = torch.nn.Sequential(pretrained_model, classifier).to(args.device)

for param in pretrained_model.parameters():
    param.requires_grad = False

print(f"Number of trainable parameters: {sum(p.numel() for p in model.parameters() if p.requires_grad)}")


# train the model
def train_one_epoch(model, dataloader, loss_fn, optimizer):
    model.train()
    size = len(dataloader.dataset)
    correct = 0
    for x, y in dataloader:
        x = x.to(args.device)
        y = y.to(args.device)

        # optimizer.zero_grad(): Clear the gradients of all optimized torch.Tensor.
        # This involves setting the .grad attribute of all parameters to None.
        optimizer.zero_grad()

        # Tensor.backward(): Compute the gradients of Tensor w.r.t. model parameters.
        # The gradients are stored in the .grad attribute of the parameters.
        logits = model(x)
        loss = loss_fn(logits, y)
        correct += (logits.argmax(1) == y).type(torch.float).sum().item()
        loss.backward()

        # optimizer.step(): Perform a single optimization step (parameter update).
        # Updates each parameter wrt the gradient stored in the parameter's .grad attribute.
        optimizer.step()
    
    accuracy = correct / size
    
    return loss.item(), accuracy

def test_model(model, dataloader, loss_fn):
    model.eval()
    size = len(dataloader.dataset)
    test_loss, correct = 0, 0
    with torch.no_grad(): # disable gradient calculation to speed up computation
        for x, y in dataloader:
            x = x.to(args.device)
            y = y.to(args.device)
            logits = model(x)
            test_loss += loss_fn(logits, y).item()
            correct += (logits.argmax(1) == y).type(torch.float).sum().item()
    test_loss /= size
    correct /= size
    return test_loss, correct

def train_model(model, x_tr, loss_fn, optimizer, num_epochs, x_val=None, scheduler=None):

    for epoch in range(num_epochs):

        t = time()

        loss, acc = train_one_epoch(model, x_tr, loss_fn, optimizer)
        
        if x_val is not None:
            test_loss, test_acc = test_model(model, x_val, loss_fn)
            val_msg = f", Test Loss: {round(test_loss, 4)}, Test Accuracy: {round(test_acc, 4)}"
        else:
            val_msg = ""

        lr = optimizer.param_groups[0]["lr"]

        if scheduler is not None:
            scheduler.step()

        print(f"Epoch {epoch+1}/{num_epochs}, Loss: {round(loss, 4)}, Accuracy: {round(acc, 4)}, Time: {round(time() - t, 4)}, LR: {lr}" + val_msg)

if __name__ == "__main__":
    
    os.makedirs(args.output_dir, exist_ok=True)
    
    weights = compute_class_weight(
        "balanced", classes=np.unique(x_tr.dataset.targets), y=x_tr.dataset.targets,
        )
    
    loss_fn = torch.nn.CrossEntropyLoss(weight=torch.tensor(weights, dtype=torch.float32).to(args.device))

    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=30, gamma=0.1)
    
    train_model(model, tr_loader, loss_fn, optimizer, args.epochs, val_loader, scheduler)

    torch.save(classifier.state_dict(), os.path.join(args.output_dir, f"classifier_fold_{args.fold}.pth"))
    
    model.eval()
    
    y_true = []
    y_pred = []
    y_entr = []
    with torch.no_grad():
        for _ in range(10): # augment the data with 10 random crops
            for x, y in val_loader:
                x = x.to(args.device)
                y = y.to(args.device)
                logits = model(x)
                proba = torch.nn.functional.softmax(logits, dim=1)
                y_true.append(y.cpu().numpy())
                y_pred.append(logits.argmax(1).cpu().numpy())
                y_entr.append(-torch.sum(proba * torch.log(proba), dim=1).cpu().numpy())
    y_true = np.concatenate(y_true)
    y_pred = np.concatenate(y_pred)
    y_entr = np.concatenate(y_entr)
    
    report = classification_report(
        y_true, y_pred, target_names=x_val.dataset.classes, output_dict=True,
        )
    
    pd.DataFrame(report).to_csv(os.path.join(args.output_dir, f"classification_report_fold_{args.fold}.csv"))
    
    e = {}
    for i in range(20):
        e[x_val.dataset.classes[i]] = y_entr[y_true == i][np.random.choice(len(y_entr[y_true == i]), 40)]
    
    pd.DataFrame(e).to_csv(os.path.join(args.output_dir, f"entropy_fold_{args.fold}.csv"))