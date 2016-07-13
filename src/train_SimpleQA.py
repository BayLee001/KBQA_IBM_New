import cPickle
import gzip
import os
import sys
sys.setrecursionlimit(6000)
import time

import numpy
import theano
import theano.tensor as T
import theano.sandbox.neighbours as TSN
import time

from logistic_sgd import LogisticRegression
from mlp import HiddenLayer
from WPDefined import ConvFoldPoolLayer, dropout_from_layer, shared_dataset, repeat_whole_matrix
from cis.deep.utils.theano import debug_print
from theano.tensor.signal import downsample
from theano.tensor.nnet import conv
from load_data import load_train_test, load_word2vec_to_init#, load_mts_wikiQA, load_wmf_wikiQA
from word2embeddings.nn.util import zero_value, random_value_normal
from common_functions import Conv_with_input_para, Average_Pooling_for_Top, create_conv_para, pythonList_into_theanoIntMatrix, Max_Pooling, cosine
from random import shuffle

from sklearn import svm
from sklearn.multiclass import OneVsRestClassifier
from sklearn.svm import LinearSVC
from sklearn.linear_model import LinearRegression

from scipy import linalg, mat, dot

# from preprocess_wikiQA import compute_map_mrr

#need to change
'''


4) fine-tune word embeddings
5) translation bettween
6) max sentence length to 40:   good and best
7) implement attention by euclid, not cosine: good
8) stop words by Yi Yang
9) normalized first word matching feature
10) only use bleu1 and nist1
11) only use bleu4 and nist5



Doesnt work:
1) lr0.08, kern30, window=5, update10
8) kern as Yu's paper
7) shuffle training data: should influence little as batch size is 1
3) use bleu and nist scores
1) true sentence lengths
2) unnormalized sentence length
8) euclid uses 1/exp(x)
'''

def evaluate_lenet5(learning_rate=0.05, n_epochs=2000, word_nkerns=10, char_nkerns=4, batch_size=1, window_width=3,
                    emb_size=50, char_emb_size=4, hidden_size=200,
                    margin=0.5, L2_weight=0.0003, update_freq=1, norm_threshold=5.0, max_truncate=40, 
                    max_char_len=40, max_des_len=20, max_relation_len=5, max_Q_len=30, train_neg_size=5, test_neg_size=5, valid_neg_size=5, neg_all=5):
#     maxSentLength=max_truncate+2*(window_width-1)
    model_options = locals().copy()
    print "model options", model_options
    rootPath='/mounts/data/proj/wenpeng/Dataset/freebase/SimpleQuestions_v2/'
    triple_files=['annotated_fb_data_train_PNQ_'+str(train_neg_size)+'nega_str&des.txt', 'annotated_fb_data_valid_PNQ_'+str(valid_neg_size)+'nega_str&des.txt', 'annotated_fb_data_test_PNQ_'+str(test_neg_size)+'nega_str&des.txt']
    question_files=['annotated_fb_data_train_mention_remainQ.txt', 'annotated_fb_data_valid_mention_remainQ.txt', 'annotated_fb_data_test_mention_remainQ.txt']
    
    rng = numpy.random.RandomState(23455)
    datasets, vocab_size, char_size=load_train_test(triple_files, question_files, max_char_len, max_des_len, max_relation_len, max_Q_len, neg_all)#max_char_len, max_des_len, max_relation_len, max_Q_len
    print 'vocab_size:', vocab_size, 'char_size:', char_size
    train_data=datasets[0]
    valid_data=datasets[1]
    test_data=datasets[2]

    train_pos_entity_char=train_data[0]
    train_pos_entity_des=train_data[1]
    train_relations=train_data[2]
    train_entity_char_lengths=train_data[3]
    train_entity_des_lengths=train_data[4]
    train_relation_lengths=train_data[5]
    train_mention_char_ids=train_data[6]
    train_remainQ_word_ids=train_data[7]
    train_mention_char_lens=train_data[8]
    train_remainQ_word_len=train_data[9]

    valid_pos_entity_char=valid_data[0]
    valid_pos_entity_des=valid_data[1]
    valid_relations=valid_data[2]
    valid_entity_char_lengths=valid_data[3]
    valid_entity_des_lengths=valid_data[4]
    valid_relation_lengths=valid_data[5]
    valid_mention_char_ids=valid_data[6]
    valid_remainQ_word_ids=valid_data[7]
    valid_mention_char_lens=valid_data[8]
    valid_remainQ_word_len=valid_data[9]

    test_pos_entity_char=test_data[0]       #matrix, each row for line example, all head and tail entity, iteratively: 40*2*51
    test_pos_entity_des=test_data[1]        #matrix, each row for a examle: 20*2*51
    test_relations=test_data[2]             #matrix, each row for a example: 5*51
    test_entity_char_lengths=test_data[3]   #matrix, each row for a example: 3*2*51  (three valies for one entity)
    test_entity_des_lengths=test_data[4]    #matrix, each row for a example: 3*2*51  (three values for one entity)
    test_relation_lengths=test_data[5]      #matrix, each row for a example: 3*51
    test_mention_char_ids=test_data[6]      #matrix, each row for a mention: 40
    test_remainQ_word_ids=test_data[7]      #matrix, each row for a question: 30
    test_mention_char_lens=test_data[8]     #matrix, each three values for a mention: 3
    test_remainQ_word_len=test_data[9]      #matrix, each three values for a remain question: 3
    
    expected_train_size=len(train_pos_entity_char)
    train_sizes=[len(train_pos_entity_char), len(train_pos_entity_des), len(train_relations), len(train_entity_char_lengths), len(train_entity_des_lengths),\
           len(train_relation_lengths), len(train_mention_char_ids), len(train_remainQ_word_ids), len(train_mention_char_lens), len(train_remainQ_word_len)]
    if sum(train_sizes)/len(train_sizes)!=expected_train_size:
        print 'weird size:', train_sizes
        exit(0)
    expected_test_size=len(test_pos_entity_char)
    test_sizes=[len(test_pos_entity_char), len(test_pos_entity_des), len(test_relations), len(test_entity_char_lengths), len(test_entity_des_lengths),\
           len(test_relation_lengths), len(test_mention_char_ids), len(test_remainQ_word_ids), len(test_mention_char_lens), len(test_remainQ_word_len)]
    if sum(test_sizes)/len(test_sizes)!=expected_test_size:
        print 'weird size:', test_sizes
        exit(0)
    n_train_batches=expected_train_size/batch_size
    n_test_batches=expected_test_size/batch_size
    
    train_batch_start=list(numpy.arange(n_train_batches)*batch_size)
    test_batch_start=list(numpy.arange(n_test_batches)*batch_size)
    
    indices_train_pos_entity_char=pythonList_into_theanoIntMatrix(train_pos_entity_char)
    indices_train_pos_entity_des=pythonList_into_theanoIntMatrix(train_pos_entity_des)
    indices_train_relations=pythonList_into_theanoIntMatrix(train_relations)
    indices_train_entity_char_lengths=pythonList_into_theanoIntMatrix(train_entity_char_lengths)
    indices_train_entity_des_lengths=pythonList_into_theanoIntMatrix(train_entity_des_lengths)
    indices_train_relation_lengths=pythonList_into_theanoIntMatrix(train_relation_lengths)
    indices_train_mention_char_ids=pythonList_into_theanoIntMatrix(train_mention_char_ids)
    indices_train_remainQ_word_ids=pythonList_into_theanoIntMatrix(train_remainQ_word_ids)
    indices_train_mention_char_lens=pythonList_into_theanoIntMatrix(train_mention_char_lens)
    indices_train_remainQ_word_len=pythonList_into_theanoIntMatrix(train_remainQ_word_len)    
    
    indices_test_pos_entity_char=pythonList_into_theanoIntMatrix(test_pos_entity_char)
    indices_test_pos_entity_des=pythonList_into_theanoIntMatrix(test_pos_entity_des)
    indices_test_relations=pythonList_into_theanoIntMatrix(test_relations)
    indices_test_entity_char_lengths=pythonList_into_theanoIntMatrix(test_entity_char_lengths)
    indices_test_entity_des_lengths=pythonList_into_theanoIntMatrix(test_entity_des_lengths)
    indices_test_relation_lengths=pythonList_into_theanoIntMatrix(test_relation_lengths)
    indices_test_mention_char_ids=pythonList_into_theanoIntMatrix(test_mention_char_ids)
    indices_test_remainQ_word_ids=pythonList_into_theanoIntMatrix(test_remainQ_word_ids)
    indices_test_mention_char_lens=pythonList_into_theanoIntMatrix(test_mention_char_lens)
    indices_test_remainQ_word_len=pythonList_into_theanoIntMatrix(test_remainQ_word_len)   


    rand_values=random_value_normal((vocab_size+1, emb_size), theano.config.floatX, numpy.random.RandomState(1234))
    rand_values[0]=numpy.array(numpy.zeros(emb_size),dtype=theano.config.floatX)
    #rand_values[0]=numpy.array([1e-50]*emb_size)
    rand_values=load_word2vec_to_init(rand_values, rootPath+'word_emb.txt')
    embeddings=theano.shared(value=rand_values, borrow=True)      

    char_rand_values=random_value_normal((char_size+1, char_emb_size), theano.config.floatX, numpy.random.RandomState(1234))
    char_rand_values[0]=numpy.array(numpy.zeros(char_emb_size),dtype=theano.config.floatX)
    char_embeddings=theano.shared(value=char_rand_values, borrow=True)      

    
    # allocate symbolic variables for the data
    index = T.lscalar()
    ent_char_ids_M = T.lmatrix()   
    ent_lens_M = T.lmatrix()
    men_char_ids = T.lvector()  
    men_lens=T.lvector()
    rel_word_ids_M=T.lmatrix()
    rel_word_lens_M=T.lmatrix()
    desH_word_ids_M=T.lmatrix()
    desH_word_lens_M=T.lmatrix()
    desT_word_ids_M=T.lmatrix()
    desT_word_lens_M=T.lmatrix()
    q_word_ids=T.lvector()
    q_word_lens=T.lvector()

#max_char_len, max_des_len, max_relation_len, max_Q_len
#     ent_men_ishape = (char_emb_size, max_char_len)  # this is the size of MNIST images
#     rel_ishape=(emb_size, max_relation_len)
#     des_ishape=(emb_size, max_des_len)
#     q_ishape=(emb_size, max_Q_len)
    
    filter_size=(emb_size,window_width)
    char_filter_size=(char_emb_size, window_width)
    #poolsize1=(1, ishape[1]-filter_size[1]+1) #?????????????????????????????
#     length_after_wideConv=ishape[1]+filter_size[1]-1
    
    ######################
    # BUILD ACTUAL MODEL #
    ######################
    print '... building the model'
    

    char_filter_shape=(char_nkerns, 1, char_filter_size[0], char_filter_size[1])
    word_filter_shape=(word_nkerns, 1, filter_size[0], filter_size[1])
    char_conv_W, char_conv_b=create_conv_para(rng, filter_shape=char_filter_shape)
    q_rel_conv_W, q_rel_conv_b=create_conv_para(rng, filter_shape=word_filter_shape)
    q_desH_conv_W, q_desH_conv_b=create_conv_para(rng, filter_shape=word_filter_shape)
    q_desT_conv_W, q_desT_conv_b=create_conv_para(rng, filter_shape=word_filter_shape)

    def SimpleQ_matches_Triple(ent_char_ids_f,ent_lens_f,rel_word_ids_f,rel_word_lens_f,desH_word_ids_f,
                       desH_word_lens_f,desT_word_ids_f,desT_word_lens_f):
#         rng = numpy.random.RandomState(23455)
        ent_char_input = char_embeddings[ent_char_ids_f.flatten()].reshape((batch_size,max_char_len, char_emb_size)).transpose(0, 2, 1).dimshuffle(0, 'x', 1, 2)
        men_char_input = char_embeddings[men_char_ids.flatten()].reshape((batch_size,max_char_len, char_emb_size)).transpose(0, 2, 1).dimshuffle(0, 'x', 1, 2)
        
        rel_word_input = embeddings[rel_word_ids_f.flatten()].reshape((batch_size,max_relation_len, emb_size)).transpose(0, 2, 1).dimshuffle(0, 'x', 1, 2)
        desH_word_input = embeddings[desH_word_ids_f.flatten()].reshape((batch_size,max_des_len, emb_size)).transpose(0, 2, 1).dimshuffle(0, 'x', 1, 2)
        
        desT_word_input = embeddings[desT_word_ids_f.flatten()].reshape((batch_size,max_des_len, emb_size)).transpose(0, 2, 1).dimshuffle(0, 'x', 1, 2)
        q_word_input = embeddings[q_word_ids.flatten()].reshape((batch_size,max_Q_len, emb_size)).transpose(0, 2, 1).dimshuffle(0, 'x', 1, 2)
    
    
        #ent_mention
        ent_char_conv = Conv_with_input_para(rng, input=ent_char_input,
                image_shape=(batch_size, 1, char_emb_size, max_char_len),
                filter_shape=char_filter_shape, W=char_conv_W, b=char_conv_b)
        men_char_conv = Conv_with_input_para(rng, input=men_char_input,
                image_shape=(batch_size, 1, char_emb_size, max_char_len),
                filter_shape=char_filter_shape, W=char_conv_W, b=char_conv_b)
        #q-rel
        q_rel_conv = Conv_with_input_para(rng, input=q_word_input,
                image_shape=(batch_size, 1, emb_size, max_Q_len),
                filter_shape=word_filter_shape, W=q_rel_conv_W, b=q_rel_conv_b)
        rel_conv = Conv_with_input_para(rng, input=rel_word_input,
                image_shape=(batch_size, 1, emb_size, max_relation_len),
                filter_shape=word_filter_shape, W=q_rel_conv_W, b=q_rel_conv_b)
        #q_desH
        q_desH_conv = Conv_with_input_para(rng, input=q_word_input,
                image_shape=(batch_size, 1, emb_size, max_Q_len),
                filter_shape=word_filter_shape, W=q_desH_conv_W, b=q_desH_conv_b)
        desH_conv = Conv_with_input_para(rng, input=desH_word_input,
                image_shape=(batch_size, 1, emb_size, max_des_len),
                filter_shape=word_filter_shape, W=q_desH_conv_W, b=q_desH_conv_b)
        #q_desT
        q_desT_conv = Conv_with_input_para(rng, input=q_word_input,
                image_shape=(batch_size, 1, emb_size, max_Q_len),
                filter_shape=word_filter_shape, W=q_desT_conv_W, b=q_desT_conv_b)
        desT_conv = Conv_with_input_para(rng, input=desT_word_input,
                image_shape=(batch_size, 1, emb_size, max_des_len),
                filter_shape=word_filter_shape, W=q_desT_conv_W, b=q_desT_conv_b)
    #     ent_char_output=debug_print(ent_char_conv.output, 'ent_char.output')
    #     men_char_output=debug_print(men_char_conv.output, 'men_char.output')
        
        
        
        ent_conv_pool=Max_Pooling(rng, input_l=ent_char_conv.output, left_l=ent_lens_f[0], right_l=ent_lens_f[2])
        men_conv_pool=Max_Pooling(rng, input_l=men_char_conv.output, left_l=men_lens[0], right_l=men_lens[2])
        
        q_rel_pool=Max_Pooling(rng, input_l=q_rel_conv.output, left_l=q_word_lens[0], right_l=q_word_lens[2])
        rel_conv_pool=Max_Pooling(rng, input_l=rel_conv.output, left_l=rel_word_lens_f[0], right_l=rel_word_lens_f[2])
        
        q_desH_pool=Max_Pooling(rng, input_l=q_desH_conv.output, left_l=q_word_lens[0], right_l=q_word_lens[2])
        desH_conv_pool=Max_Pooling(rng, input_l=desH_conv.output, left_l=desH_word_lens_f[0], right_l=desH_word_lens_f[2])
        
        q_desT_pool=Max_Pooling(rng, input_l=q_desT_conv.output, left_l=q_word_lens[0], right_l=q_word_lens[2])
        desT_conv_pool=Max_Pooling(rng, input_l=desT_conv.output, left_l=desT_word_lens_f[0], right_l=desT_word_lens_f[2])    
        
        
        overall_simi=cosine(ent_conv_pool.output_maxpooling, men_conv_pool.output_maxpooling)+\
                    cosine(q_rel_pool.output_maxpooling, rel_conv_pool.output_maxpooling)+\
                    cosine(q_desH_pool.output_maxpooling, desH_conv_pool.output_maxpooling)+\
                    cosine(q_desT_pool.output_maxpooling, desT_conv_pool.output_maxpooling)
        return overall_simi
    
    simi_list, updates = theano.scan(
        SimpleQ_matches_Triple,
        sequences=[ent_char_ids_M,ent_lens_M,rel_word_ids_M,rel_word_lens_M,desH_word_ids_M,
                   desH_word_lens_M,desT_word_ids_M,desT_word_lens_M])
    
    posi_simi=simi_list[0]
    nega_simies=simi_list[1:]
    loss_simi_list=T.maximum(0.0, margin-posi_simi.reshape((1,1))+nega_simies) 
    loss_simi=T.sum(loss_simi_list)

    

    
    #L2_reg =(layer3.W** 2).sum()+(layer2.W** 2).sum()+(layer1.W** 2).sum()+(conv_W** 2).sum()
    L2_reg =debug_print((char_embeddings** 2).sum()+(embeddings** 2).sum()+(char_conv_W** 2).sum()+(q_rel_conv_W** 2).sum()+(q_desH_conv_W** 2).sum()+(q_desT_conv_W** 2).sum(), 'L2_reg')#+(layer1.W** 2).sum()++(embeddings**2).sum()

    cost=loss_simi+L2_weight*L2_reg
    #cost=debug_print((cost_this+cost_tmp)/update_freq, 'cost')
    

    
    test_model = theano.function([index], [loss_simi,simi_list],
          givens={
            ent_char_ids_M : indices_test_pos_entity_char[index].reshape(((test_neg_size+1)*2, max_char_len))[::2],  
            ent_lens_M : indices_test_entity_char_lengths[index].reshape(((test_neg_size+1)*2, 3))[::2],
            men_char_ids : indices_test_mention_char_ids[index],
            men_lens : indices_test_mention_char_lens[index],
            rel_word_ids_M : indices_test_relations[index].reshape((test_neg_size+1, max_relation_len)),
            rel_word_lens_M : indices_test_relation_lengths[index].reshape((test_neg_size+1, 3)),
            desH_word_ids_M : indices_test_pos_entity_des[index].reshape(((test_neg_size+1)*2, max_des_len))[::2], 
            desH_word_lens_M : indices_test_entity_des_lengths[index].reshape(((test_neg_size+1)*2, 3))[::2],
            desT_word_ids_M : indices_test_pos_entity_des[index].reshape(((test_neg_size+1)*2, max_des_len))[1::2], 
            desT_word_lens_M : indices_test_entity_des_lengths[index].reshape(((test_neg_size+1)*2, 3))[1::2],
            q_word_ids : indices_test_remainQ_word_ids[index],
            q_word_lens : indices_test_remainQ_word_len[index]}, on_unused_input='ignore')


    #params = layer3.params + layer2.params + layer1.params+ [conv_W, conv_b]
    params = [char_embeddings, embeddings, char_conv_W, char_conv_b, q_rel_conv_W, q_rel_conv_b, q_desH_conv_W, q_desH_conv_b, q_desT_conv_W, q_desT_conv_b]#+[embeddings]# + layer1.params 
#     params_conv = [conv_W, conv_b]
    
    accumulator=[]
    for para_i in params:
        eps_p=numpy.zeros_like(para_i.get_value(borrow=True),dtype=theano.config.floatX)
        accumulator.append(theano.shared(eps_p, borrow=True))
      
    # create a list of gradients for all model parameters
    grads = T.grad(cost, params)

    updates = []
    for param_i, grad_i, acc_i in zip(params, grads, accumulator):
        grad_i=debug_print(grad_i,'grad_i')
        acc = acc_i + T.sqr(grad_i)
#         updates.append((param_i, param_i - learning_rate * grad_i / T.sqrt(acc+1e-10)))   #AdaGrad
#         updates.append((acc_i, acc))    
        if param_i == embeddings:
            updates.append((param_i, T.set_subtensor((param_i - learning_rate * grad_i / T.sqrt(acc+1e-10))[0], theano.shared(numpy.zeros(emb_size)))))   #Ada
        elif param_i == char_embeddings:
            updates.append((param_i, T.set_subtensor((param_i - learning_rate * grad_i / T.sqrt(acc+1e-10))[0], theano.shared(numpy.zeros(char_emb_size)))))   #AdaGrad
        else:
            updates.append((param_i, param_i - learning_rate * grad_i / T.sqrt(acc+1e-10)))   #AdaGrad
        updates.append((acc_i, acc)) 
  
    train_model = theano.function([index], [loss_simi, cost], updates=updates,
          givens={
            ent_char_ids_M : indices_train_pos_entity_char[index].reshape(((train_neg_size+1)*2, max_char_len))[::2],  
            ent_lens_M : indices_train_entity_char_lengths[index].reshape(((train_neg_size+1)*2, 3))[::2],
            men_char_ids : indices_train_mention_char_ids[index],
            men_lens : indices_train_mention_char_lens[index],
            rel_word_ids_M : indices_train_relations[index].reshape((train_neg_size+1, max_relation_len)),
            rel_word_lens_M : indices_train_relation_lengths[index].reshape((train_neg_size+1, 3)),
            desH_word_ids_M : indices_train_pos_entity_des[index].reshape(((train_neg_size+1)*2, max_des_len))[::2], 
            desH_word_lens_M : indices_train_entity_des_lengths[index].reshape(((train_neg_size+1)*2, 3))[::2],
            desT_word_ids_M : indices_train_pos_entity_des[index].reshape(((train_neg_size+1)*2, max_des_len))[1::2], 
            desT_word_lens_M : indices_train_entity_des_lengths[index].reshape(((train_neg_size+1)*2, 3))[1::2],
            q_word_ids : indices_train_remainQ_word_ids[index],
            q_word_lens : indices_train_remainQ_word_len[index]}, on_unused_input='ignore')




    ###############
    # TRAIN MODEL #
    ###############
    print '... training'
    # early-stopping parameters
    patience = 500000000000000  # look as this many examples regardless
    patience_increase = 2  # wait this much longer when a new best is
                           # found
    improvement_threshold = 0.995  # a relative improvement of this much is
                                   # considered significant
    validation_frequency = min(n_train_batches, patience / 2)
                                  # go through this many
                                  # minibatche before checking the network
                                  # on the validation set; in this case we
                                  # check every epoch

    best_params = None
    best_validation_loss = numpy.inf
    best_iter = 0
    test_score = 0.
    start_time = time.clock()
    mid_time = start_time

    epoch = 0
    done_looping = False
    
    best_test_accu=0.0

    while (epoch < n_epochs) and (not done_looping):
        epoch = epoch + 1
        #for minibatch_index in xrange(n_train_batches): # each batch
        minibatch_index=0

#         ent_char_ids_M_train = indices_train_pos_entity_char[index].reshape(((train_neg_size+1)*2, max_char_len))[::2],  
#         ent_lens_M : indices_train_entity_char_lengths[index].reshape(((train_neg_size+1)*2, 3))[::2],
#         men_char_ids : indices_train_mention_char_ids[index],
#         men_lens : indices_train_mention_char_lens[index],
#         rel_word_ids_M : indices_train_relations[index].reshape((train_neg_size+1, max_relation_len)),
#         rel_word_lens_M : indices_train_relation_lengths[index].reshape((train_neg_size+1, 3)),
#         desH_word_ids_M : indices_train_pos_entity_des[index].reshape(((train_neg_size+1)*2, max_des_len))[::2], 
#         desH_word_lens_M : indices_train_entity_des_lengths[index].reshape(((train_neg_size+1)*2, 3))[::2],
#         desT_word_ids_M : indices_train_pos_entity_des[index].reshape(((train_neg_size+1)*2, max_des_len))[1::2], 
#         desT_word_lens_M : indices_train_entity_des_lengths[index].reshape(((train_neg_size+1)*2, 3))[1::2],
#         q_word_ids : indices_train_remainQ_word_ids[index],
#         q_word_lens : indices_train_remainQ_word_len[index]}, on_unused_input='ignore')

        for batch_start in train_batch_start: 
            # iter means how many batches have been runed, taking into loop
            iter = (epoch - 1) * n_train_batches + minibatch_index +1

            minibatch_index=minibatch_index+1
            #print batch_start
            loss_simi_i, cost_i= train_model(batch_start)
            if batch_start%10==0:
                print batch_start, 'loss_simi_i: ', loss_simi_i, 'cost_i:', cost_i

            if iter % n_train_batches == 0:
                print 'training @ iter = '+str(iter)+'loss_simi_i: ', loss_simi_i, 'cost_i:', cost_i
            #if iter ==1:
            #    exit(0)
            
            if iter % validation_frequency == 0:
                #write_file=open('log.txt', 'w')
                test_loss=[]
                succ=0
                for i in test_batch_start:
                    loss_simi_i,simi_list_i=test_model(i)
                    test_loss.append(loss_simi_i)
                    if simi_list_i[0]>=max(simi_list_i[1:]):
                        succ+=1

                succ=succ*1.0/len(expected_test_size)
                #now, check MAP and MRR
                print(('\t\t\t\t\t\tepoch %i, minibatch %i/%i, test accu of best '
                           'model %f') %
                          (epoch, minibatch_index, n_train_batches,succ))

                if best_test_accu< succ:
                    best_test_accu=succ
                    store_model_to_file(rootPath, params)
            if patience <= iter:
                done_looping = True
                break
        print 'Epoch ', epoch, 'uses ', (time.clock()-mid_time)/60.0, 'min'
        mid_time = time.clock() 

            
        #print 'Batch_size: ', update_freq
    end_time = time.clock()
    print('Optimization complete.')
    print('Best validation score of %f %% obtained at iteration %i,'\
          'with test performance %f %%' %
          (best_validation_loss * 100., best_iter + 1, test_score * 100.))
    print >> sys.stderr, ('The code for file ' +
                          os.path.split(__file__)[1] +
                          ' ran for %.2fm' % ((end_time - start_time) / 60.))


def store_model_to_file(path, best_params):
    save_file = open(path+'Best_Conv_Para', 'wb')  # this will overwrite current contents
    for para in best_params:           
        cPickle.dump(para.get_value(borrow=True), save_file, -1)  # the -1 is for HIGHEST_PROTOCOL
    save_file.close()
    print 'Better model stored'

# def cosine(vec1, vec2):
#     vec1=debug_print(vec1, 'vec1')
#     vec2=debug_print(vec2, 'vec2')
#     norm_uni_l=T.sqrt((vec1**2).sum())
#     norm_uni_r=T.sqrt((vec2**2).sum())
#     
#     dot=T.dot(vec1,vec2.T)
#     
#     simi=debug_print(dot/(norm_uni_l*norm_uni_r), 'uni-cosine')
#     return simi.reshape((1,1))    
def Linear(sum_uni_l, sum_uni_r):
    return (T.dot(sum_uni_l,sum_uni_r.T)).reshape((1,1))    
def Poly(sum_uni_l, sum_uni_r):
    dot=T.dot(sum_uni_l,sum_uni_r.T)
    poly=(0.5*dot+1)**3
    return poly.reshape((1,1))    
def Sigmoid(sum_uni_l, sum_uni_r):
    dot=T.dot(sum_uni_l,sum_uni_r.T)
    return T.tanh(1.0*dot+1).reshape((1,1))    
def RBF(sum_uni_l, sum_uni_r):
    eucli=T.sum((sum_uni_l-sum_uni_r)**2)
    return T.exp(-0.5*eucli).reshape((1,1))    
def GESD (sum_uni_l, sum_uni_r):
    eucli=1/(1+T.sum((sum_uni_l-sum_uni_r)**2))
    kernel=1/(1+T.exp(-(T.dot(sum_uni_l,sum_uni_r.T)+1)))
    return (eucli*kernel).reshape((1,1))   
def EUCLID(sum_uni_l, sum_uni_r):
    return T.sqrt(T.sqr(sum_uni_l-sum_uni_r).sum()+1e-20).reshape((1,1))
    


if __name__ == '__main__':
    evaluate_lenet5()