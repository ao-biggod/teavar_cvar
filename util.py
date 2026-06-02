import itertools
import numpy as np
from scipy.stats import weibull_min

try:
    from tqdm import tqdm
except ImportError:
    # 如果没有安装 tqdm，提供一个简单的 fallback
    def tqdm(iterable, *args, **kwargs):
        return iterable

####################################################################################
#######################  Print Results of TEAVAR formulation  ########################
####################################################################################

def print_results(o, alpha, a, u, umax, edges, scenarios, T, Tf, L, capacity, verbose=False, utilization=True):
    print(f"Objective value: {o}\n")
    print("------------------ Allocations ----------------------\n")
    
    # 假设 a 是一个二维数组/列表 (nflows x ntunnels)
    for i in range(len(a)):
        for j in range(len(a[i])):
            print(f"Flow {i}, tunnel {j} allocated : {a[i][j]}")
            print("Edges in use: ", end="")
            for e in T[Tf[i][j]]:
                print(edges[e], end="")
            print("\n")
            
    if verbose:
        print("--------------- Loss Breakdown ---------------------\n")
        for s in range(len(umax)):
            if s == 0:
                print(f"Scenario 0 (No failures): {scenarios[s]}")
            else:
                print(f"Scenario {s}: {scenarios[s]}")
            
            print("Edges: ", end="")
            for i in range(len(scenarios[s])):
                if scenarios[s][i] == 0.0:
                    print(edges[i], end=" ")
            print("go down\n")

            for f in range(len(u[s])):
                print(f"Loss on flow {f} = {u[s][f]}")
            
            print(f"umax = {umax[s]}")
            print(f"Max loss = {umax[s] + alpha}\n")
            
    print("------------------------------------------------\n")
    
    if utilization:
        for e in range(len(edges)):
            print(f"EDGE: {e} : {edges[e]}")
            print(f"capacity: {capacity[e]}")
            s_val = 0
            for f in range(len(a)):
                for t in range(len(a[f])):
                    # L 是 隧道 x 边的可用性矩阵
                    s_val += a[f][t] * L[Tf[f][t]][e]
            print(f"used: {s_val}\n")


####################################################################################
###################  Compute all possible scenario bitmaps  ########################
####################################################################################

def k_scenarios(nedges, k, probabilities, first=True):
    scenarios = []
    if first:
        scenario = [1.0] * nedges
        scenarios.append(scenario)
        
    for i in range(1, k + 1):
        for bits in itertools.combinations(range(nedges), i):
            s = [1.0] * nedges
            for bit in bits:
                s[bit] = 0.0
            scenarios.append(s)
            
    probs = get_probabilities(scenarios, probabilities)
    return scenarios, probs

def all_scenarios(nedges, probabilities, first=True):
    scenarios = []
    probs = []
    
    if first:
        scenario = [1.0] * nedges
        scenarios.append(scenario) # ADD SCENARIO NO FAILURES
        prob = 1.0
        for i in range(len(scenario)):
            prob *= (1 - scenario[i]) * probabilities[i] + scenario[i] * (1 - probabilities[i])
        probs.append(prob)
        
    for i in tqdm(range(1, nedges + 1), desc="Computing all scenarios..."):
        for bits in itertools.combinations(range(nedges), i):
            s = [1.0] * nedges
            for bit in bits:
                s[bit] = 0.0
            prob = 1.0
            for j in range(len(s)):
                prob *= (1 - s[j]) * probabilities[j] + s[j] * (1 - probabilities[j])
            probs.append(prob)
            scenarios.append(s)
            
    total_prob = sum(probs)
    normalized_probs = [p / total_prob for p in probs]
    return scenarios, normalized_probs


####################################################################################
####################  Get probabilities of all scenarios  ##########################
####################################################################################

def get_probabilities(scenarios, probabilities):
    nscenarios = len(scenarios)
    p = []
    for s in range(nscenarios):
        prob = 1.0
        for i in range(len(scenarios[s])):
            prob *= (1 - scenarios[s][i]) * probabilities[i] + scenarios[s][i] * (1 - probabilities[i])
        p.append(prob)
    return p


####################################################################################
####################  Compute all scenarios above a threshold  #####################
####################################################################################

def sub_scenarios_recursion(original, cutoff, remaining=None, offset=0, partial=None, scenarios=None, probabilities=None):
    # 避免 Python 中可变默认参数带来的陷阱
    if remaining is None: remaining = original
    if partial is None: partial = []
    if scenarios is None: scenarios = []
    if probabilities is None: probabilities = []

    if len(partial) == 0:  # first run
        scenarios.append([1.0] * len(original))
        prob_no_failure = np.prod([1 - p for p in original])
        probabilities.append(prob_no_failure)
        remaining = original
    else:
        probs = [1 - p for p in original]
        bitmap = [1.0] * len(original)  # create bitmap
        for index in partial:
            probs[index] = original[index]
            bitmap[index] = 0.0
            
        product = np.prod(probs)
        
        if product >= cutoff:
            scenarios.append(bitmap)
            probabilities.append(product)
        else:
            return scenarios, probabilities

    for i in range(len(remaining)):
        new_offset = len(original) - len(remaining)
        n = new_offset + i
        # 递归调用时，创建 partial 和 remaining 的新副本
        sub_scenarios_recursion(
            original, 
            cutoff, 
            remaining=remaining[i+1:], 
            offset=new_offset, 
            partial=partial + [n], 
            scenarios=scenarios, 
            probabilities=probabilities
        )
        
    return scenarios, probabilities

def sub_scenarios(original, cutoff, first=True, last=True):
    print(f"Computing scenarios cutoff={cutoff}...")
    scenarios, probabilities = sub_scenarios_recursion(original, cutoff)
    
    if not first:
        scenarios = scenarios[1:]
        probabilities = probabilities[1:]
        
    if last:
        # 添加一个所有链路全挂掉的极端兜底场景
        scenarios.append([0.0] * len(scenarios[0]))
        probabilities.append(1.0 - sum(probabilities))
        
    total_p = sum(probabilities)
    if 0 < total_p < 1.0:
        probabilities = [p / total_p for p in probabilities]
        
    return scenarios, probabilities


####################################################################################
####################  Weibull Distribution probabilities  #######################
####################################################################################

def weibull_probs(num, shape=0.8, scale=0.0001):
    # scipy.stats.weibull_min 函数中：shape 等于 c，scale 等于 scale
    return weibull_min.rvs(shape, scale=scale, size=num).tolist()