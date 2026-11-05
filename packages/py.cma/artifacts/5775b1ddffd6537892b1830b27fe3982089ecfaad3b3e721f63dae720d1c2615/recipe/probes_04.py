"""Bounded numerical operations for the final exact-original-wheel candidates."""
from pathlib import Path
import profile_probes as base
from profile_probes import require,raises


def cma_probe(m,work):
    import numpy as np
    options={'seed':1729,'popsize':6,'verbose':-9,'verb_log':0,'verb_disp':0,
             'verb_filenameprefix':str(work/'cma-'),'maxiter':12}
    optimizer=m.CMAEvolutionStrategy([2.,-3.],0.8,options)
    observed=[]
    for _ in range(12):
        points=optimizer.ask()
        require(len(points)==6 and all(np.asarray(x).shape==(2,) for x in points),'CMA sample population shape differs')
        fitness=[float(np.dot(x,x)) for x in points]
        optimizer.tell(points,fitness);observed.append(min(fitness))
    require(optimizer.countiter==12 and optimizer.result.fbest<1.0 and np.isfinite(optimizer.result.xbest).all(),'CMA ask/tell search did not improve bounded quadratic objective')
    rejected=m.CMAEvolutionStrategy([1.,1.],0.5,options)
    population=rejected.ask()
    raises(ValueError,lambda:rejected.tell(population,[1.0]),'Mismatched population/fitness lengths were accepted')
    return {'checks':['real-cma-ask-tell','deterministic-population-shape','quadratic-objective-improvement','iteration-accounting','mismatched-fitness-rejection'],
            'initial_objective':13.0,'best_objective':float(optimizer.result.fbest),'iterations':optimizer.countiter,
            'scope':'A bounded local numerical optimization smoke contract; no optimizer quality benchmark or general convergence claim.'}


def contourpy_probe(m,work):
    import numpy as np
    x=np.array([0.,1.,2.]);y=np.array([0.,1.,2.]);z=np.tile(x,(3,1))
    generator=m.contour_generator(x=x,y=y,z=z,name='serial',line_type='Separate',fill_type='OuterCode')
    lines=generator.lines(0.5)
    require(len(lines)==1 and np.allclose(lines[0][:,0],0.5) and np.isclose(lines[0][:,1].min(),0) and np.isclose(lines[0][:,1].max(),2),'Native contour line coordinates differ')
    polygons,codes=generator.filled(0.25,1.75)
    require(len(polygons)==len(codes)==1,'Filled contour topology differs')
    vertices=polygons[0];area=abs(float(np.dot(vertices[:,0],np.roll(vertices[:,1],-1))-np.dot(vertices[:,1],np.roll(vertices[:,0],-1))))/2
    require(np.isclose(area,3.) and codes[0][0]==1 and codes[0][-1]==79,'Filled contour geometry/path codes differ')
    raises(ValueError,lambda:generator.filled(1.0,0.5),'Reversed filled-contour levels were accepted')
    return {'checks':['real-native-contour-generator','level-line-coordinates','filled-polygon-area','path-codes','reversed-levels-rejection'],'filled_area':area}


PROBES={'cma':cma_probe,'contourpy':contourpy_probe}
base.PROBES.update(PROBES)
main=base.main
