import os
import numpy as np
from itertools import islice

def read_topology(topology_name, base_path, downscale=1.0):
    dir_path = os.path.join(base_path, topology_name)
    
    # 1. 读取节点
    with open(os.path.join(dir_path, "nodes.txt"), "r") as f:
        lines = f.readlines()[1:] # 跳过标题
        input_nodes = [line.strip() for line in lines if line.strip()]
        
    links = []
    capacity = []
    probabilities = []
    
    # 2. 读取拓扑
    with open(os.path.join(dir_path, "topology.txt"), "r") as f:
        lines = f.readlines()
        for line in lines:
            parts = line.strip().split()
            if not parts or parts[0] == "to_node": continue
            
            try:
                # 原始文件格式: to_node | from_node | capacity | prob
                to_node = int(parts[0])
                from_node = int(parts[1])
                cap_raw = float(parts[2])
                prob = float(parts[3])
                
                # 转换索引为 0-based
                src, dst = from_node - 1, to_node - 1
                
                # 关键：严格对齐 Julia 换算逻辑
                # capacity = 原值 / downscale / 1000
                cap_final = cap_raw / downscale / 1000.0
                
                links.append((src, dst))
                capacity.append(cap_final)
                probabilities.append(prob)
            except (ValueError, IndexError):
                continue
                
    return links, capacity, probabilities, input_nodes

def read_demand(topology_name, num_nodes, base_path, num_demand=0, scale=1.0, downscale=1.0):
    demand_path = os.path.join(base_path, topology_name, "demand.txt")
    all_data = np.loadtxt(demand_path)
    
    if all_data.ndim == 1:
        target_row = all_data
    else:
        # 读取指定行
        target_row = all_data[num_demand] if num_demand < len(all_data) else all_data[-1]
    
    flows = []
    demands = []
    
    # 矩阵展平解析 (12x12 = 144)
    for i in range(num_nodes * num_nodes):
        src = i // num_nodes
        dst = i % num_nodes
        val = target_row[i]
        
        if src != dst and val > 0:
            flows.append((src, dst))
            # 关键：严格对齐 Julia 换算逻辑
            # demand = 原值 / downscale * scale / 1000
            demands.append(val / downscale * scale / 1000.0)
                
    return np.array(demands), flows

def get_tunnels(nodes, edges, flows, k=4):
    import networkx as nx

    G = nx.DiGraph()
    edge_to_idx = {edge: i for i, edge in enumerate(edges)}
    for src, dst in edges:
        G.add_edge(src, dst, weight=1.0)

    T = []
    Tf = []
    current_idx = 0
    
    for src, dst in flows:
        f_tunnels = []
        try:
            paths = list(islice(nx.shortest_simple_paths(G, src, dst, weight='weight'), k))
            for p in paths:
                edge_indices = []
                for i in range(len(p) - 1):
                    e = (p[i], p[i+1])
                    edge_indices.append(edge_to_idx[e])
                T.append(edge_indices)
                f_tunnels.append(current_idx)
                current_idx += 1
        except nx.NetworkXNoPath:
            pass
        Tf.append(f_tunnels)
        
    return T, Tf, k