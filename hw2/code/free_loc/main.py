import argparse
import os
import shutil
import time
import sys
sys.path.insert(0,'../faster_rcnn')
sys.path.insert(0,'../')

import sklearn
import sklearn.metrics
import visdom

import torch
import torch.nn as nn
import torch.nn.parallel
import torch.nn.functional as F
import torch.backends.cudnn as cudnn
import torch.distributed as dist
import torch.optim as optim
import torch.utils.data
import torch.utils.data.distributed
import torchvision.transforms as transforms
import torchvision.datasets as datasets
import torchvision.models as models

from datasets.factory import get_imdb
from custom import *
from logger import *
model_names = sorted(name for name in models.__dict__
    if name.islower() and not name.startswith("__")
    and callable(models.__dict__[name]))

parser = argparse.ArgumentParser(description='PyTorch ImageNet Training')
parser.add_argument('--arch', default='localizer_alexnet')
parser.add_argument('-j', '--workers', default=4, type=int, metavar='N',
                    help='number of data loading workers (default: 4)')
parser.add_argument('--epochs', default=2, type=int, metavar='N',
                    help='number of total epochs to run')
parser.add_argument('--start-epoch', default=0, type=int, metavar='N',
                    help='manual epoch number (useful on restarts)')
parser.add_argument('-b', '--batch-size', default=256, type=int,
                    metavar='N', help='mini-batch size (default: 256)')
parser.add_argument('--lr', '--learning-rate', default=0.1, type=float,
                    metavar='LR', help='initial learning rate')
parser.add_argument('--momentum', default=0.9, type=float, metavar='M',
                    help='momentum')
parser.add_argument('--weight-decay', '--wd', default=1e-4, type=float,
                    metavar='W', help='weight decay (default: 1e-4)')
parser.add_argument('--print-freq', '-p', default=10, type=int,
                    metavar='N', help='print frequency (default: 10)')
parser.add_argument('--eval-freq', default=10, type=int,
                    metavar='N', help='print frequency (default: 10)')
parser.add_argument('--resume', default='', type=str, metavar='PATH',
                    help='path to latest checkpoint (default: none)')
parser.add_argument('-e', '--evaluate', dest='evaluate', action='store_true',
                    help='evaluate model on validation set')
parser.add_argument('--pretrained', dest='pretrained', action='store_true',
                    help='use pre-trained model')
parser.add_argument('--world-size', default=1, type=int,
                    help='number of distributed processes')
parser.add_argument('--dist-url', default='tcp://224.66.41.62:23456', type=str,
                    help='url used to set up distributed training')
parser.add_argument('--dist-backend', default='gloo', type=str,
                    help='distributed backend')
parser.add_argument('--vis',action='store_true')

best_prec1 = 0


def main():
    global args, best_prec1
    args = parser.parse_args()
    args.distributed = args.world_size > 1
    numpy.random.seed(5)

    # create model
    print("=> creating model '{}'".format(args.arch))
    if args.arch=='localizer_alexnet':
        model = localizer_alexnet(pretrained=args.pretrained)
    elif args.arch=='localizer_alexnet_robust':
        model = localizer_alexnet_robust(pretrained=args.pretrained)
    print(model)

    model.features = torch.nn.DataParallel(model.features)
    model.cuda()

    # TODO:
    # define loss function (criterion) and optimizer
    optimizer = optim.SGD(model.parameters(), lr = args.lr, momentum=0.9)
    criterion = nn.MultiLabelSoftMarginLoss()

    
    # optionally resume from a checkpoint
    if args.resume:
        if os.path.isfile(args.resume):
            print("=> loading checkpoint '{}'".format(args.resume))
            checkpoint = torch.load(args.resume)
            args.start_epoch = checkpoint['epoch']
            best_prec1 = checkpoint['best_prec1']
            model.load_state_dict(checkpoint['state_dict'])
            optimizer.load_state_dict(checkpoint['optimizer'])
            print("=> loaded checkpoint '{}' (epoch {})"
                  .format(args.resume, checkpoint['epoch']))
        else:
            print("=> no checkpoint found at '{}'".format(args.resume))

    cudnn.benchmark = True

    # Data loading code
    # TODO: Write code for IMDBDataset in custom.py
    trainval_imdb = get_imdb('voc_2007_trainval')
    test_imdb = get_imdb('voc_2007_test')

    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                     std=[0.229, 0.224, 0.225])
    train_dataset = IMDBDataset(
        trainval_imdb,
        transforms.Compose([
            transforms.Resize((512,512)),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            normalize,
        ]))
    train_sampler = None
    train_loader = torch.utils.data.DataLoader(
        train_dataset, batch_size=args.batch_size, shuffle=(train_sampler is None),
        num_workers=args.workers, pin_memory=True, sampler=train_sampler)

    val_loader = torch.utils.data.DataLoader(
        IMDBDataset(test_imdb, transforms.Compose([
            transforms.Resize((384,384)),
            transforms.ToTensor(),
            normalize,
        ])),
        batch_size=args.batch_size, shuffle=False,
        num_workers=args.workers, pin_memory=True)

    if args.evaluate:
        validate(val_loader, model, criterion)
        return

    # TODO: Create loggers for visdom and tboard
    # TODO: You can pass the logger objects to train(), make appropriate
    # modifications to train()
    logger_t = Logger('./tboard', name='freeloc')
    logger_v = visdom.Visdom(server='http://localhost',port='8097')
    #logger_v = Logger('./visdom', name='freeloc')




    for epoch in range(args.start_epoch, args.epochs):
        adjust_learning_rate(optimizer, epoch)

        
        # train for one epoch
        train(train_loader, model, criterion, optimizer, epoch, logger_t, logger_v)

        # evaluate on validation set
        if epoch%args.eval_freq==0 or epoch==args.epochs-1:
            m1, m2 = validate(val_loader, model, criterion)
            score = m1*m2
            # remember best prec@1 and save checkpoint
            is_best =  score > best_prec1
            best_prec1 = max(score, best_prec1)
            save_checkpoint({
                'epoch': epoch + 1,
                'arch': args.arch,
                'state_dict': model.state_dict(),
                'best_prec1': best_prec1,
                'optimizer' : optimizer.state_dict(),
            }, is_best)


#TODO: You can add input arguments if you wish
def train(train_loader, model, criterion, optimizer, epoch, logger_t, logger_v):
    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()
    avg_m1 = AverageMeter()
    avg_m2 = AverageMeter()

    # switch to train mode
    model.train()

    end = time.time()
    print(len(train_loader))
    # i goes from 0 to 5010/batchsize 
    max_i = 5010/args.batch_size  #5010 is lenght of data set
    max_i_div = int(max_i/4)  #since we want to plot images for 4 batches
    
    for i, (input, target) in enumerate(train_loader):
        # measure data loading time
        data_time.update(time.time() - end)

        target = target.type(torch.FloatTensor).cuda(async=True)
        input_var = torch.autograd.Variable(input, requires_grad=True)
        target_var = torch.autograd.Variable(target)

        # TODO: Get output from model
        # TODO: Perform any necessary functions on the output
        # TODO: Compute loss using ``criterion``
        
            # compute output**
        output = model(input_var)
        
        #print(output.size())
        max_out = F.max_pool2d(output, kernel_size=output.size()[-1])
        
        imoutput = max_out.squeeze()
        #imoutput = out.transpose(1,2)
        
        loss = criterion(imoutput, target_var)
        
        # measure metrics and record loss
        m1 = metric1(imoutput.data, target)
        m2 = metric2(imoutput.data, target)
        losses.update(loss.data[0], input.size(0))
        avg_m1.update(m1[0], input.size(0))
        avg_m2.update(m2[0], input.size(0))
        
        # TODO: 
        # compute gradient and do SGD step

        optimizer.zero_grad()   #zeros out all buffer for gradients from optimizer
        loss.backward()
        optimizer.step()

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()
        
        if i % args.print_freq == 0:
            print('Epoch: [{0}][{1}/{2}]\t'
                  'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                  'Data {data_time.val:.3f} ({data_time.avg:.3f})\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Metric1 {avg_m1.val:.3f} ({avg_m1.avg:.3f})\t'
                  'Metric2 {avg_m2.val:.3f} ({avg_m2.avg:.3f})'.format(
                   epoch, i, len(train_loader), batch_time=batch_time,
                   data_time=data_time, loss=losses, avg_m1=avg_m1,
                   avg_m2=avg_m2))
            # log the loss value
            logger_t.scalar_summary(tag= 'loss', value= loss, step= (i+1)*epoch)
        #print(i)
        
        #TODO: Visualize things as mentioned in handout
        #TODO: Visualize at appropriate intervals
        if i % max_i_div == 0:
            for b_idx in range(target.size()[0]):
                if b_idx > 4: 
                    break
                img_name = train_loader.dataset.imdb.image_path_at(b_idx+ i*args.batch_size)[-11:-1]
                logger_t.image_summary(tag = 'imgs batch:' + str(b_idx), images =input[b_idx,:,:,:], step=epoch)
#                train_img = input[b_idx].cpu().numpy()*((np.array([[[0.229]], [[0.224]], [[0.225]]])+             np.array([[[0.485]], [[0.456]], [[0.406]]]))*255).astype(np.uint8)
                #input_np = input[b_idx].cpu().numpy();
                #train_img = (255 * (input_np - np.max(input_np))/np.ptp(input_np)).astype(np.uint8)
                train_img = input[b_idx]
                train_img = train_img.numpy()
                train_img = train_img * np.array([0.229, 0.224, 0.225]).reshape((3,1,1))
                train_img = train_img + np.array([0.485, 0.456, 0.406]).reshape((3,1,1))
                train_img = (train_img * 256).astype(np.uint8)
                
                #print(train_img.size())
                title = "_".join((str(epoch), str((i+1)*epoch), str(b_idx), img_name)) 
                logger_v.image(
                    train_img,
                    opts=dict(title=title),
                )
                h, w = input.size()[2], input.size()[3]
                cnt = sum(target[b_idx][:])
                
                #heatmap = torch.tensor(cnt,3,h,w)
                #label_cnt = 0
                #upsmapler = nn.Upsample(size = (h,w))
                for j in range(target.size()[1]):
                    if target[b_idx][j] == 1:
                        #gray = upsmapler(output[i][j][:][:]) #Only 3D, 4D and 5D input Tensors 
                        #supported, does not work
                        a = np.array(output[b_idx][j][:][:].data)
                        #print(a.shape)
                        m = Image.fromarray(a*256).convert('RGB') 
                        m = m.resize((h,w))
                        
                        clr = cv2.applyColorMap(np.array(m) ,cv2.COLORMAP_JET)
                        #print(clr.shape)
                        #heatmap[label_cnt][:][:][:] = clr
                        ### Tensorflow
                        logger_t.image_summary(tag =  'heat map batch:' + str(b_idx), images= np.array(m), step=epoch)
                        ### Visdom
                        title = "_".join((str(epoch), str((i+1)*epoch), str(b_idx), 'heatmap', img_name, train_loader.dataset.idx_to_cls[j]))
                        logger_v.image(
                            clr.transpose((2,0,1)),
                            opts=dict(title=title)
                        )
        
        
def validate(val_loader, model, criterion):
    batch_time = AverageMeter()
    losses = AverageMeter()
    avg_m1 = AverageMeter()
    avg_m2 = AverageMeter()


    # switch to evaluate mode
    model.eval()

    end = time.time()
    for i, (input, target) in enumerate(val_loader):
        target = target.type(torch.FloatTensor).cuda(async=True)
        input_var = torch.autograd.Variable(input, volatile=True)
        target_var = torch.autograd.Variable(target, volatile=True)

        # TODO: Get output from model
        # TODO: Perform any necessary functions on the output
        # TODO: Compute loss using ``criterion``
        # compute output

        output = model(input_var)
        max_out = F.max_pool2d(output, kernel_size=output.size()[-1])
        imoutput = max_out.squeeze()
        loss = criterion(imoutput, target_var)


        # measure metrics and record loss
        m1 = metric1(imoutput.data, target)
        m2 = metric2(imoutput.data, target)
        losses.update(loss.data[0], input.size(0))
        avg_m1.update(m1[0], input.size(0))
        avg_m2.update(m2[0], input.size(0))

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.print_freq == 0:
            print('Test: [{0}/{1}]\t'
                  'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Metric1 {avg_m1.val:.3f} ({avg_m1.avg:.3f})\t'
                  'Metric2 {avg_m2.val:.3f} ({avg_m2.avg:.3f})'.format(
                   i, len(val_loader), batch_time=batch_time, loss=losses,
                   avg_m1=avg_m1, avg_m2=avg_m2))

        #TODO: Visualize things as mentioned in handout
        #TODO: Visualize at appropriate intervals
        #
        



    print(' * Metric1 {avg_m1.avg:.3f} Metric2 {avg_m2.avg:.3f}'
          .format(avg_m1=avg_m1, avg_m2=avg_m2))

    return avg_m1.avg, avg_m2.avg


# TODO: You can make changes to this function if you wish (not necessary)
def save_checkpoint(state, is_best, filename='checkpoint.pth.tar'):
    torch.save(state, filename)
    if is_best:
        shutil.copyfile(filename, 'model_best.pth.tar')


class AverageMeter(object):
    """Computes and stores the average and current value"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count


def adjust_learning_rate(optimizer, epoch):
    """Sets the learning rate to the initial LR decayed by 10 every 30 epochs"""
    lr = args.lr * (0.1 ** (epoch // 30))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


def metric1(output, target):
    # TODO: Ignore for now - proceed till instructed
    #size Nxk
    target = np.array(target)
    output = np.array(output)
    all_ap = np.zeros((target.shape[1]))
    for cls in range(output.shape[1]):
        
        gt = target[:][cls]
        pred = output[:][cls]
        pred -= 1e-5 * gt    # Subtract eps from score to make AP work for tied scores
        all_ap[cls] = sklearn.metrics.average_precision_score(gt, pred, average=None)
    return all_ap

def metric2(output, target,th = 0.5):
    # TODO: Ignore for now - proceed till instructed
    def false_neg(y_true, y_pred):
              return np.sum((1. - y_pred) * y_true)
    def true_pos(y_true, y_pred):
              return np.sum(y_true * y_pred)
    
    target = np.array(target)
    target = target.astype('float')
    output = np.array(output)
    output = (output > th).astype('float')
    all_ap = np.zeros((target.shape[1]))
    micro = np.zeros((target.shape[1]))
    macro = np.zeros((target.shape[1]))
    weighted = np.zeros((target.shape[1]))
    for cls in range(output.shape[1]):
        gt = target[:][cls]
        pred = output[:][cls]
        tp = true_pos(gt,pred)
        #fn = false_neg(gt,pred)
        #all_ap[cls] = tp/(tp+fn)
        #micro[cls] = sklearn.metrics.recall_score(gt, pred, average='micro')
        all_ap[cls] = sklearn.metrics.recall_score(gt, pred, average='macro')
        #weighted[cls] = sklearn.metrics.recall_score(gt, pred, average='weighted')
 
    #     print('micro', np.mean(micro))
    #     print('macro', np.mean(macro))
    #     print('weighted', np.mean(weighted))
    return all_ap

if __name__ == '__main__':
    main()
